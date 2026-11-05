# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import (
    api_error, api_response, parse_int, require_auth, require_recent_auth, require_step_up,
)

from .common import (
    ENROL_MAX_FRAMES, ENROL_MIN_FRAMES, analyze_enrolment_frames, consent_dict, face_status,
    is_face_manager, notify, read_frames, read_payload,
)

UNAVAILABLE_MESSAGES = {
    'disabled': 'Face login is not enabled at this school.',
    'role_not_allowed': 'Face login is not available for this account.',
    'consent_required': "A parent must agree to face login for this student first.",
    'inactive': 'This account is not active.',
}


def _own_parent(env):
    return env['op.parent'].sudo().search([('user_id', '=', env.user.id)], limit=1)


def _subject(env, student_id):
    """(user, student, error) for whose face is being managed: the caller
    when `student_id` is empty, else a child linked to the calling parent."""
    if not student_id:
        return env.user.sudo(), env['op.student'], None
    student_id, error = parse_int(student_id, 'student_id')
    if error:
        return None, None, error
    parent = _own_parent(env)
    student = env['op.student'].sudo().browse(student_id)
    if not parent or not student.exists() or student not in parent.student_ids:
        return None, None, api_error('This student is not linked to your account.', status=403, code='forbidden')
    return student.user_id, student, None


def _flag(value):
    return value is True or value in ('1', 'true', 'True', 1)


class BxiFaceSelfServiceController(http.Controller):

    @http.route('/api/v1/face/status', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def status(self, **kwargs):
        """Face-login state of the caller and, for a parent, each child."""
        env = request.env
        user = env.user.sudo()
        data = {
            'face_login_enabled': bool(user.company_id.bxi_face_enabled),
            'self': face_status(user),
            'children': [],
        }
        parent = _own_parent(env)
        for student in parent.student_ids:
            data['children'].append(dict(
                face_status(student.user_id),
                student_id=student.id,
                name=student.name,
                has_account=bool(student.user_id),
                consent=consent_dict(student),
            ))
        return api_response(data)

    @http.route('/api/v1/face/consent', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @require_step_up
    def consent(self, **kwargs):
        """A parent agrees to (granted: true) or withdraws (granted: false)
        face login for their child. Withdrawing deletes the child's face
        data straight away."""
        env = request.env
        payload, _files, error = read_payload()
        if error:
            return error
        if not payload.get('student_id') or 'granted' not in payload:
            return api_error('student_id and granted are required.', status=400, code='missing_fields')
        user, student, error = _subject(env, payload['student_id'])
        if error:
            return error
        if _flag(payload['granted']):
            env['bxi.face.consent'].sudo()._grant(student, env.user)
        else:
            consent = env['bxi.face.service']._active_consent(student)
            if consent:
                consent._withdraw(env.user)
        return api_response(dict(face_status(user), student_id=student.id, consent=consent_dict(student)))

    @http.route('/api/v1/face/enroll', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @require_recent_auth
    def enroll(self, **kwargs):
        """Register a face: 3-5 photos (one looking straight at the camera,
        optionally a couple with the head slightly turned), for yourself or
        - as a parent - for a linked child. Staff approve it before it can
        be used. Needs a password/OTP confirmation in the last few minutes
        (a fresh password/OTP login counts)."""
        env = request.env
        payload, files, error = read_payload()
        if error:
            return error
        user, student, error = _subject(env, payload.get('student_id'))
        if error:
            return error
        if student and not user:
            return api_error("This student doesn't have an app account yet. Ask the school to create one.",
                             status=400, code='student_has_no_account')
        company = user.company_id
        if not company.bxi_face_enabled:
            return api_error(UNAVAILABLE_MESSAGES['disabled'], status=403, code='disabled')

        Service = env['bxi.face.service']
        consent_given = _flag(payload.get('consent'))
        own_student = Service._school_records(user)[0]
        consent_by = env.user.sudo()
        if student:
            if consent_given:
                env['bxi.face.consent'].sudo()._grant(student, env.user)
            source = 'parent'
        else:
            source = 'self'
            if own_student:
                # A student can't consent for themselves; a parent must have.
                consent = Service._active_consent(own_student)
                consent_by = consent.granted_by_id if consent else None
        if not consent_given and not (student or own_student):
            return api_error('Agree to face login (consent: true) to continue.', status=400, code='consent_required')
        if (student or own_student) and company.bxi_face_student_consent_required \
                and not Service._active_consent(student or own_student):
            return api_error(UNAVAILABLE_MESSAGES['consent_required'], status=400, code='consent_required')

        ok, reason = Service._eligibility(user)
        if not ok:
            return api_error(UNAVAILABLE_MESSAGES.get(reason, 'Face login is not available.'),
                             status=403, code=reason)

        frames, error = read_frames(payload, files, ENROL_MIN_FRAMES, ENROL_MAX_FRAMES)
        if error:
            return error
        analyses, actions, error = analyze_enrolment_frames(frames)
        if error:
            return error

        enrolment = env['bxi.face.enrolment'].sudo()._create_from_analyses(
            user, analyses, source, env.user.sudo(), consent_by=consent_by, actions=actions)
        managers = env.ref('bxi_face_auth.group_face_manager').sudo().all_user_ids.filtered(
            lambda manager: company in manager.company_ids and is_face_manager(manager))
        notify(managers, 'Face login photos to review',
               '%s submitted face login photos for review.' % user.name, record=enrolment)
        return api_response(dict(face_status(user), enrolment_id=enrolment.id))

    @http.route('/api/v1/face/disable', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @require_step_up
    def disable(self, **kwargs):
        """Turn face login off for yourself or a linked child; the face
        data is deleted. (Withdrawing a child's consent does this too.)"""
        env = request.env
        payload, _files, error = read_payload()
        if error:
            return error
        user, student, error = _subject(env, payload.get('student_id'))
        if error:
            return error
        if user:
            env['bxi.face.enrolment'].sudo().search([
                ('user_id', '=', user.id), ('state', 'in', ('active', 'pending')),
            ])._end('revoked', 'turned off by a parent' if student else 'turned off by the user')
        return api_response(face_status(user))
