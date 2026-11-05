# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, rate_limit, require_auth, require_step_up

REVIEWER_GROUPS = ('bxi_identity_verification.group_identity_reviewer', 'base.group_system')

SUBJECT_MODELS = {
    'student': 'op.student',
    'parent': 'op.parent',
}


def _own_parent_record(env):
    return env['op.parent'].sudo().search([('user_id', '=', env.user.id)], limit=1)


def _resolve_subject(env, subject_type, subject_id):
    """Returns (subject_record, error_response). Enforces that the caller
    is either an identity reviewer, the parent record itself, or a parent
    linked to the student in question.

    "Staff" here means the Identity Reviewer group, not base.group_user:
    family accounts are often internal users in this deployment, and a
    plain internal user must not be able to read or replace the Aadhaar
    number or face photo of someone else's child.
    """
    model_name = SUBJECT_MODELS.get(subject_type)
    if not model_name:
        return None, api_error("subject_type must be 'student' or 'parent'.", status=400, code='invalid_subject_type')

    subject = env[model_name].sudo().browse(int(subject_id))
    if not subject.exists():
        return None, api_error('Record not found.', status=404, code='not_found')

    if any(env.user.has_group(group) for group in REVIEWER_GROUPS):
        return subject, None

    own_parent = _own_parent_record(env)
    if subject_type == 'parent' and own_parent and own_parent.id == subject.id:
        return subject, None
    if subject_type == 'student' and own_parent and subject.id in own_parent.student_ids.ids:
        return subject, None

    return None, api_error('Not authorized for this record.', status=403, code='forbidden')


class BxiIdentityVerificationController(http.Controller):

    @http.route('/api/v1/identity/status', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def status(self, subject_type=None, subject_id=None, **kwargs):
        if not subject_type or not subject_id:
            return api_error('subject_type and subject_id are required.', status=400, code='missing_fields')
        subject, error = _resolve_subject(request.env, subject_type, subject_id)
        if error:
            return error
        return api_response({
            'aadhar_verification_status': subject.aadhar_verification_status,
            'face_verification_status': subject.face_verification_status,
        })

    @http.route('/api/v1/identity/aadhar/submit', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @require_step_up
    def submit_aadhar(self, **kwargs):
        payload = request.get_json_data()
        subject_type = payload.get('subject_type')
        subject_id = payload.get('subject_id')
        aadhar_number = (payload.get('aadhar_number') or '').strip()
        if not subject_type or not subject_id or not aadhar_number:
            return api_error('subject_type, subject_id and aadhar_number are required.', status=400, code='missing_fields')

        subject, error = _resolve_subject(request.env, subject_type, subject_id)
        if error:
            return error
        try:
            subject.sudo()._submit_aadhar(aadhar_number)
        except UserError as exc:
            return api_error(str(exc), status=400, code='invalid_aadhar')
        return api_response({'aadhar_verification_status': subject.aadhar_verification_status})

    @http.route('/api/v1/identity/face/submit', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @require_step_up
    def submit_face(self, **kwargs):
        payload = request.get_json_data()
        subject_type = payload.get('subject_type')
        subject_id = payload.get('subject_id')
        image = payload.get('image')
        if not subject_type or not subject_id or not image:
            return api_error('subject_type, subject_id and image are required.', status=400, code='missing_fields')

        subject, error = _resolve_subject(request.env, subject_type, subject_id)
        if error:
            return error
        try:
            subject.sudo()._submit_face(image)
        except UserError as exc:
            return api_error(str(exc), status=400, code='invalid_image')
        return api_response({'face_verification_status': subject.face_verification_status})

    @http.route('/api/v1/identity/link-student', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('link_student', limit=10)
    @require_auth
    @require_step_up
    def link_student(self, **kwargs):
        """Add a child to the calling parent's account. The parent proves
        they know the child by sending the registration number (`gr_no`)
        and date of birth exactly as the school recorded them; a student
        id alone (a guessable sequence number) is not enough. Any mismatch
        - unknown number, wrong date, or a record without a date of birth -
        gets the same answer, so the route can't be used to look students up.
        """
        payload = request.get_json_data()
        parent = _own_parent_record(request.env)
        if not parent:
            return api_error('No parent record is linked to this account.', status=403, code='not_a_parent')

        gr_no = (payload.get('gr_no') or '').strip()
        birth_date_raw = (payload.get('birth_date') or '').strip()
        if not gr_no or not birth_date_raw:
            return api_error('gr_no and birth_date are required.', status=400, code='missing_fields')
        try:
            birth_date = fields.Date.from_string(birth_date_raw)
        except ValueError:
            return api_error('birth_date must be a date (YYYY-MM-DD).', status=400, code='invalid_birth_date')

        students = request.env['op.student'].sudo().search([('gr_no', '=', gr_no)], limit=2)
        student_id = payload.get('student_id')
        if (len(students) != 1 or not students.birth_date or students.birth_date != birth_date
                or (student_id and str(student_id) != str(students.id))):
            return api_error(
                "These details don't match the school's records. Please contact the school office.",
                status=403, code='verification_failed')

        parent.sudo().write({'student_ids': [(4, students.id)]})
        return api_response({'linked_student_ids': parent.student_ids.ids})

    @http.route('/api/v1/identity/unlink-student', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @require_step_up
    def unlink_student(self, **kwargs):
        payload = request.get_json_data()
        student_id = payload.get('student_id')
        if not student_id:
            return api_error('student_id is required.', status=400, code='missing_fields')

        parent = _own_parent_record(request.env)
        if not parent:
            return api_error('No parent record is linked to this account.', status=403, code='not_a_parent')

        if list(parent.student_ids.ids) == [int(student_id)]:
            return api_error('Cannot remove the last linked student.', status=400, code='last_student')

        parent.sudo().write({'student_ids': [(3, int(student_id))]})
        return api_response({'linked_student_ids': parent.student_ids.ids})
