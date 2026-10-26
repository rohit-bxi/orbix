# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Elective subject choice (openeducat_core's op.subject.registration): the
family picks electives from the class's elective subjects and submits;
an academic coordinator approves, which writes the subjects onto the
student's enrollment."""
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import get_viewable_student, parse_ids, ref, running_enrollment, safe_create, school_context

REVIEWER_GROUPS = (
    'bxi_academic_management.group_academic_coordinator',
    'bxi_academic_management.group_academic_manager',
    'openeducat_core.group_op_back_office_admin',
)
REVIEW_ACTIONS = {
    'approve': ('action_approve', ('submitted',)),
    'reject': ('action_reject', ('submitted',)),
    'reset-to-draft': ('action_reset_draft', ('rejected',)),
}


def _is_reviewer(user):
    return any(user.has_group(group) for group in REVIEWER_GROUPS)


def _registration_dict(reg):
    return {
        'id': reg.id,
        'name': reg.name,
        'student': ref(reg.student_id),
        'class': ref(reg.course_id),
        'section': ref(reg.batch_id),
        'compulsory_subjects': [ref(s) for s in reg.compulsory_subject_ids],
        'elective_subjects': [ref(s) for s in reg.elective_subject_ids],
        'available_electives': [ref(s) for s in reg.course_id.subject_ids.filtered(
            lambda s: s.subject_type == 'elective')],
        'state': reg.state,
    }


class BxiApiSupportSubjectRegistrationController(http.Controller):

    @http.route('/api/v1/subject-registrations', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_registrations(self, state=None, **kwargs):
        """Family: their students' registrations. Reviewers: all."""
        Registration = request.env['op.subject.registration'].sudo()
        if _is_reviewer(request.env.user):
            domain = []
        else:
            domain = [('student_id', 'in', school_context(request.env)['students'].ids)]
        if state:
            domain.append(('state', '=', state))
        return api_response({'registrations': [_registration_dict(r) for r in Registration.search(domain)]})

    @http.route('/api/v1/subject-registrations', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_registration(self, **kwargs):
        """{student_id, elective_subject_ids}: a draft for the student's
        current class, with its compulsory subjects filled in."""
        payload = request.get_json_data() or {}
        context = school_context(request.env)
        student, error = get_viewable_student(
            request.env, payload.get('student_id'), allow=lambda env, s: s in context['students'])
        if error:
            return error
        enrollment = running_enrollment(student)
        if not enrollment:
            return api_error('The student has no current class.', status=400, code='not_enrolled')
        elective_ids, error = parse_ids(payload.get('elective_subject_ids') or [], 'elective_subject_ids')
        if error:
            return error
        offered = enrollment.course_id.subject_ids.filtered(lambda s: s.subject_type == 'elective').ids
        if set(elective_ids) - set(offered):
            return api_error("Some electives aren't offered for this class.", status=400, code='invalid_elective')
        registration, error = safe_create(request.env['op.subject.registration'].sudo(), {
            'student_id': student.id, 'course_id': enrollment.course_id.id, 'batch_id': enrollment.batch_id.id,
            'elective_subject_ids': [(6, 0, elective_ids)],
        })
        if error:
            return error
        registration.get_subjects()
        return api_response(_registration_dict(registration), status=201)

    @http.route('/api/v1/subject-registrations/<int:registration_id>/submit', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def submit(self, registration_id, **kwargs):
        registration = request.env['op.subject.registration'].sudo().browse(registration_id)
        if not registration.exists() or registration.student_id not in school_context(request.env)['students']:
            return api_error('Registration not found.', status=404, code='not_found')
        if registration.state != 'draft':
            return api_error('Only a draft registration can be submitted.', status=400, code='invalid_transition')
        _, error = call_action(registration, 'action_submitted')
        if error:
            return error
        return api_response(_registration_dict(registration))

    @http.route('/api/v1/subject-registrations/<int:registration_id>/<any("approve", "reject", "reset-to-draft"):action>',
                type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def review(self, registration_id, action, **kwargs):
        if not _is_reviewer(request.env.user):
            return api_error('Only academic coordinators can review subject choices.', status=403, code='forbidden')
        registration = request.env['op.subject.registration'].sudo().browse(registration_id)
        if not registration.exists():
            return api_error('Registration not found.', status=404, code='not_found')
        method, allowed_from = REVIEW_ACTIONS[action]
        if registration.state not in allowed_from:
            return api_error(f"Can't {action} a registration that is {registration.state}.",
                             status=400, code='invalid_transition')
        _, error = call_action(registration, method)
        if error:
            return error
        return api_response(_registration_dict(registration))
