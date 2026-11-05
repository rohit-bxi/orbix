# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

import base64
from datetime import datetime, time, timedelta
from functools import wraps

from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth
from odoo.addons.bxi_api_support.controllers.common import parse_date, parse_ids, parse_pagination

from ..models.face_login_attempt import ATTEMPT_RESULTS
from .common import (
    ENROL_MAX_FRAMES, analyze_enrolment_frames, dt, is_face_manager, notify, person, read_frames, read_payload,
)

ENROLMENT_STATES = ('pending', 'active', 'rejected', 'revoked', 'expired')
ROLE_FIELDS = {'student': 'student_id', 'teacher': 'faculty_id', 'parent': 'parent_id'}
KIOSK_ROLES = ('student', 'teacher', 'parent', 'staff')
ATTEMPT_MODES = ('phone', 'auto', 'kiosk', 'identify')

# API name -> (res.company field, type, min, max)
SETTINGS = {
    'enabled': ('bxi_face_enabled', 'bool', None, None),
    'allow_student': ('bxi_face_allow_student', 'bool', None, None),
    'allow_teacher': ('bxi_face_allow_teacher', 'bool', None, None),
    'allow_parent': ('bxi_face_allow_parent', 'bool', None, None),
    'allow_staff': ('bxi_face_allow_staff', 'bool', None, None),
    'student_consent_required': ('bxi_face_student_consent_required', 'bool', None, None),
    'student_class_ids': ('bxi_face_student_course_ids', 'ids', None, None),
    'kiosk_enabled': ('bxi_face_kiosk_enabled', 'bool', None, None),
    'auto_identify_enabled': ('bxi_face_auto_identify', 'bool', None, None),
    'match_threshold': ('bxi_face_match_threshold', 'float', 0.2, 0.95),
    'kiosk_match_threshold': ('bxi_face_kiosk_match_threshold', 'float', 0.2, 0.95),
    'kiosk_match_gap': ('bxi_face_kiosk_match_gap', 'float', 0.0, 0.5),
    'liveness_required': ('bxi_face_liveness_required', 'bool', None, None),
    'antispoof_threshold': ('bxi_face_antispoof_threshold', 'float', 0.0, 1.0),
    'max_failures': ('bxi_face_max_failures', 'int', 1, 20),
    'lockout_minutes': ('bxi_face_lockout_minutes', 'int', 1, 1440),
    'student_validity_days': ('bxi_face_student_validity_days', 'int', 0, 3650),
    'token_days': ('bxi_face_token_days', 'int', 1, 365),
    'attempt_retention_days': ('bxi_face_attempt_retention_days', 'int', 1, 3650),
    'consent_version': ('bxi_face_consent_version', 'char', None, None),
}


def manager_only(func):
    """Use below @require_auth: system admins and Face Login Managers."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not is_face_manager(request.env.user):
            return api_error('You do not have access to face login administration.', status=403, code='forbidden')
        return func(*args, **kwargs)
    return wrapper


def _companies():
    return request.env.user.company_ids


def _class_name(student):
    running = student.course_detail_ids.filtered(lambda line: line.state == 'running')[:1]
    if not running:
        return None
    return ' / '.join(name for name in (running.course_id.name, running.batch_id.name) if name)


def _enrolment_dict(enrolment, with_photos=False):
    Service = request.env['bxi.face.service']
    student, faculty, parent = enrolment.student_id, enrolment.faculty_id, enrolment.parent_id
    data = {
        'id': enrolment.id,
        'state': enrolment.state,
        'source': enrolment.source,
        'user': person(enrolment.user_id),
        'roles': Service._face_roles(enrolment.user_id),
        'student': {'id': student.id, 'name': student.name, 'gr_no': student.gr_no or None,
                    'class': _class_name(student)} if student else None,
        'teacher': {'id': faculty.id, 'name': faculty.name} if faculty else None,
        'parent': {'id': parent.id, 'name': parent.name.name} if parent else None,
        'submitted_by': person(enrolment.submitted_by_id),
        'submitted_at': dt(enrolment.create_date),
        'consent': {
            'given_by': person(enrolment.consent_by_id),
            'at': dt(enrolment.consent_at),
            'version': enrolment.consent_version or None,
        } if enrolment.consent_by_id else None,
        'reviewed_by': person(enrolment.reviewed_by_id),
        'reviewed_at': dt(enrolment.reviewed_at),
        'reject_reason': enrolment.reject_reason or None,
        'activated_at': dt(enrolment.activated_at),
        'expires_at': dt(enrolment.expires_at),
        'ended_at': dt(enrolment.ended_at),
        'end_reason': enrolment.end_reason or None,
        'model_version': enrolment.model_version or None,
        'duplicates': [person(user) for user in enrolment.duplicate_user_ids],
        'same_person': [person(user) for user in enrolment.same_person_user_ids],
        'photo_count': len(enrolment.template_ids),
    }
    if with_photos:
        data['photos'] = [{
            'id': template.id,
            'action': template.action or None,
            'yaw': round(template.yaw, 3),
            'detection_score': round(template.det_score, 3),
            'face_pixels': template.face_pixels,
            'sharpness': round(template.sharpness, 1),
        } for template in enrolment.template_ids]
    return data


def _get_enrolment(enrolment_id):
    enrolment = request.env['bxi.face.enrolment'].sudo().browse(enrolment_id)
    if not enrolment.exists() or enrolment.company_id not in _companies():
        return None, api_error('Enrolment not found.', status=404, code='not_found')
    return enrolment, None


def _kiosk_dict(kiosk):
    return {
        'id': kiosk.id,
        'name': kiosk.name,
        'active': kiosk.active,
        'roles': kiosk._allowed_roles(),
        'session_minutes': kiosk.session_minutes,
        'key_last4': kiosk.key_last4,
        'last_used_at': dt(kiosk.last_used_at),
        'created_by': person(kiosk.created_by_id),
    }


def _settings_dict(company):
    Service = request.env['bxi.face.service']
    data = {}
    for name, (field, kind, _low, _high) in SETTINGS.items():
        value = company[field]
        if kind == 'ids':
            value = [{'id': course.id, 'name': course.name} for course in value]
        elif kind == 'float':
            value = round(value, 3)
        elif kind == 'char':
            value = value or None
        data[name] = value
    Enrolment = request.env['bxi.face.enrolment'].sudo()
    data.update({
        'engine': Service._engine_status(),
        'encryption_key_source': Service._key_source(),
        'enrolments': {
            state: Enrolment.search_count([('company_id', '=', company.id), ('state', '=', state)])
            for state in ('active', 'pending')
        },
    })
    return data


def _resolve_same_person(payload, allowed):
    """(users, error): the duplicates the reviewer says are the same person."""
    raw = payload.get('same_person_user_ids') or []
    ids, error = parse_ids(raw, 'same_person_user_ids')
    if error:
        return None, error
    users = request.env['res.users'].sudo().browse(ids).exists()
    if users - allowed or len(users) != len(ids):
        return None, api_error('same_person_user_ids must be accounts listed as duplicates.',
                               status=400, code='invalid_same_person_user_ids')
    return users, None


def _check_duplicates(enrolment, payload):
    """Approval needs an explicit decision when the face matches other
    enrolled accounts: name them as the same person, or say they aren't
    (ignore_duplicates)."""
    duplicates = enrolment._recheck_duplicates()
    same, error = _resolve_same_person(payload, duplicates)
    if error:
        return None, error
    if (duplicates - same) and payload.get('ignore_duplicates') is not True:
        body = {'success': False, 'error': {
            'message': 'This face matches other enrolled accounts. Mark them as the same person '
                       '(same_person_user_ids) or confirm they are different people (ignore_duplicates: true).',
            'code': 'duplicate_review_required',
            'duplicates': [person(user) for user in duplicates],
        }}
        return None, request.make_json_response(body, status=409)
    return same, None


class BxiFaceAdminController(http.Controller):

    # -- enrolments -----------------------------------------------------------------

    @http.route('/api/v1/admin/face/enrolments', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    @manager_only
    def list_enrolments(self, state=None, role=None, search=None, user_id=None, **kwargs):
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [('company_id', 'in', _companies().ids)]
        if state:
            if state not in ENROLMENT_STATES:
                return api_error('state must be one of: %s.' % ', '.join(ENROLMENT_STATES), status=400, code='invalid_state')
            domain.append(('state', '=', state))
        if role:
            if role not in ROLE_FIELDS:
                return api_error('role must be student, teacher or parent.', status=400, code='invalid_role')
            domain.append((ROLE_FIELDS[role], '!=', False))
        if user_id:
            user_id, error = parse_int(user_id, 'user_id')
            if error:
                return error
            domain.append(('user_id', '=', user_id))
        if search:
            domain += ['|', ('user_id.name', 'ilike', search), ('user_id.login', 'ilike', search)]
        Enrolment = request.env['bxi.face.enrolment'].sudo()
        order = 'create_date asc, id asc' if state == 'pending' else 'create_date desc, id desc'
        enrolments = Enrolment.search(domain, limit=limit, offset=offset, order=order)
        return api_response(
            [_enrolment_dict(enrolment) for enrolment in enrolments],
            meta={'total': Enrolment.search_count(domain), 'limit': limit, 'offset': offset})

    @http.route('/api/v1/admin/face/enrolments/<int:enrolment_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    @manager_only
    def get_enrolment(self, enrolment_id, **kwargs):
        enrolment, error = _get_enrolment(enrolment_id)
        if error:
            return error
        return api_response(_enrolment_dict(enrolment, with_photos=True))

    @http.route('/api/v1/admin/face/enrolments/<int:enrolment_id>/photos', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    @manager_only
    def enrolment_photos(self, enrolment_id, **kwargs):
        """The submitted photos (base64 JPEG) next to the photo already on
        the school record, for comparing before approving."""
        enrolment, error = _get_enrolment(enrolment_id)
        if error:
            return error
        photos = []
        for template in enrolment.template_ids:
            image = template._get_image()
            photos.append({
                'id': template.id,
                'action': template.action or None,
                'image': base64.b64encode(image).decode() if image else None,
            })
        record = enrolment.student_id or enrolment.faculty_id or enrolment.parent_id.name
        record_photo = record.image_1920 if record else False
        return api_response({
            'enrolment_id': enrolment.id,
            'photos': photos,
            'record_photo': record_photo.decode() if isinstance(record_photo, bytes) else (record_photo or None),
        })

    @http.route('/api/v1/admin/face/enrolments/<int:enrolment_id>/approve', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @manager_only
    def approve_enrolment(self, enrolment_id, **kwargs):
        env = request.env
        enrolment, error = _get_enrolment(enrolment_id)
        if error:
            return error
        if enrolment.state != 'pending':
            return api_error('Only pending enrolments can be approved.', status=400, code='invalid_state')
        payload, _files, error = read_payload()
        if error:
            return error
        Service = env['bxi.face.service']
        if enrolment.student_id and enrolment.company_id.bxi_face_student_consent_required \
                and not Service._active_consent(enrolment.student_id):
            return api_error('There is no parental consent on record for this student.',
                             status=400, code='consent_required')
        same, error = _check_duplicates(enrolment, payload)
        if error:
            return error
        enrolment._activate(env.user, same)
        recipients = enrolment.user_id | enrolment.submitted_by_id
        notify(recipients, 'Face login is ready',
               'Face login has been approved for %s.' % enrolment.user_id.name, record=enrolment)
        return api_response(_enrolment_dict(enrolment))

    @http.route('/api/v1/admin/face/enrolments/<int:enrolment_id>/reject', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @manager_only
    def reject_enrolment(self, enrolment_id, **kwargs):
        enrolment, error = _get_enrolment(enrolment_id)
        if error:
            return error
        if enrolment.state != 'pending':
            return api_error('Only pending enrolments can be rejected.', status=400, code='invalid_state')
        payload, _files, error = read_payload()
        if error:
            return error
        reason = (payload.get('reason') or '').strip()
        enrolment._reject(request.env.user, reason)
        notify(enrolment.user_id | enrolment.submitted_by_id, 'Face login photos not accepted',
               reason or 'The photos could not be accepted. Please take new ones.', record=enrolment)
        return api_response(_enrolment_dict(enrolment))

    @http.route('/api/v1/admin/face/enrolments/<int:enrolment_id>/revoke', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @manager_only
    def revoke_enrolment(self, enrolment_id, **kwargs):
        enrolment, error = _get_enrolment(enrolment_id)
        if error:
            return error
        if enrolment.state not in ('active', 'pending'):
            return api_error('Only active or pending enrolments can be revoked.', status=400, code='invalid_state')
        payload, _files, error = read_payload()
        if error:
            return error
        enrolment._end('revoked', (payload.get('reason') or '').strip() or 'revoked by staff')
        return api_response(_enrolment_dict(enrolment))

    @http.route('/api/v1/admin/face/enrol', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @manager_only
    def staff_enrol(self, **kwargs):
        """In-person enrolment at the school desk: active immediately,
        unless the face matches another enrolled account (then it stays
        pending until approved with a duplicates decision). Identify the
        person with one of user_id, student_id, faculty_id or parent_id.
        For a student without consent on record, send consent_reference
        (e.g. the signed form number)."""
        env = request.env
        payload, files, error = read_payload()
        if error:
            return error
        keys = [key for key in ('user_id', 'student_id', 'faculty_id', 'parent_id') if payload.get(key)]
        if len(keys) != 1:
            return api_error('Send exactly one of user_id, student_id, faculty_id or parent_id.',
                             status=400, code='missing_fields')
        record_id, error = parse_int(payload[keys[0]], keys[0])
        if error:
            return error
        model = {'user_id': 'res.users', 'student_id': 'op.student',
                 'faculty_id': 'op.faculty', 'parent_id': 'op.parent'}[keys[0]]
        record = env[model].sudo().browse(record_id).exists()
        if not record:
            return api_error('Record not found.', status=404, code='not_found')
        user = record if model == 'res.users' else record.user_id
        if not user:
            return api_error('This person has no app account yet.', status=400, code='no_account')
        if user.company_id not in _companies():
            return api_error('Record not found.', status=404, code='not_found')

        Service = env['bxi.face.service']
        student = Service._school_records(user)[0]
        consent_by = user
        if student:
            consent = Service._active_consent(student)
            reference = (payload.get('consent_reference') or '').strip()
            if not consent and reference:
                consent = env['bxi.face.consent'].sudo()._grant(student, env.user, method='offline', reference=reference)
            if not consent and user.company_id.bxi_face_student_consent_required:
                return api_error('Record the parent\'s consent first (consent_reference: the signed form number).',
                                 status=400, code='consent_required')
            consent_by = consent.granted_by_id if consent else None

        frames, error = read_frames(payload, files, 1, ENROL_MAX_FRAMES)
        if error:
            return error
        analyses, actions, error = analyze_enrolment_frames(frames)
        if error:
            return error
        enrolment = env['bxi.face.enrolment'].sudo()._create_from_analyses(
            user, analyses, 'staff', env.user, consent_by=consent_by, actions=actions)
        if not enrolment.duplicate_user_ids:
            enrolment._activate(env.user)
        return api_response(_enrolment_dict(enrolment))

    # -- attempts ------------------------------------------------------------------------

    @http.route('/api/v1/admin/face/attempts', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    @manager_only
    def list_attempts(self, user_id=None, result=None, mode=None, kiosk_id=None, date_from=None, date_to=None, **kwargs):
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [('company_id', 'in', _companies().ids)]
        if user_id:
            user_id, error = parse_int(user_id, 'user_id')
            if error:
                return error
            domain += ['|', ('user_id', '=', user_id), ('target_user_ids', 'in', user_id)]
        if result:
            if result not in dict(ATTEMPT_RESULTS):
                return api_error('Unknown result.', status=400, code='invalid_result')
            domain.append(('result', '=', result))
        if mode:
            if mode not in ATTEMPT_MODES:
                return api_error('mode must be one of: %s.' % ', '.join(ATTEMPT_MODES), status=400, code='invalid_mode')
            domain.append(('mode', '=', mode))
        if kiosk_id:
            kiosk_id, error = parse_int(kiosk_id, 'kiosk_id')
            if error:
                return error
            domain.append(('kiosk_id', '=', kiosk_id))
        for value, operator, name in ((date_from, '>=', 'date_from'), (date_to, '<', 'date_to')):
            if value:
                day, error = parse_date(value, name)
                if error:
                    return error
                if operator == '<':
                    day = day + timedelta(days=1)
                domain.append(('create_date', operator, datetime.combine(day, time.min)))
        Attempt = request.env['bxi.face.login.attempt'].sudo()
        attempts = Attempt.search(domain, limit=limit, offset=offset)
        return api_response([{
            'id': attempt.id,
            'at': dt(attempt.create_date),
            'mode': attempt.mode,
            'kiosk': {'id': attempt.kiosk_id.id, 'name': attempt.kiosk_id.name} if attempt.kiosk_id else None,
            'ip': attempt.ip or None,
            'device_name': attempt.device_name or None,
            'login_hint': attempt.login_hint or None,
            'accounts_tried': [person(user) for user in attempt.target_user_ids],
            'user': person(attempt.user_id),
            'result': attempt.result,
            'reason': attempt.reason or None,
            'best_score': round(attempt.best_score, 3),
            'second_score': round(attempt.second_score, 3),
            'live_score': round(attempt.live_score, 3) if attempt.live_score else None,
        } for attempt in attempts], meta={'total': Attempt.search_count(domain), 'limit': limit, 'offset': offset})

    # -- kiosks ----------------------------------------------------------------------------

    @http.route('/api/v1/admin/face/kiosks', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    @manager_only
    def list_kiosks(self, **kwargs):
        kiosks = request.env['bxi.face.kiosk'].sudo().with_context(active_test=False).search(
            [('company_id', 'in', _companies().ids)])
        return api_response([_kiosk_dict(kiosk) for kiosk in kiosks])

    @http.route('/api/v1/admin/face/kiosks', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @manager_only
    def create_kiosk(self, **kwargs):
        """Register a kiosk. The response holds its key once; put it in the
        kiosk app's settings - it can't be shown again."""
        payload, _files, error = read_payload()
        if error:
            return error
        name = (payload.get('name') or '').strip()
        if not name:
            return api_error('name is required.', status=400, code='missing_fields')
        roles = payload.get('roles', ['student', 'teacher'])
        if not isinstance(roles, list) or not roles or any(role not in KIOSK_ROLES for role in roles):
            return api_error('roles must be a non-empty list of: %s.' % ', '.join(KIOSK_ROLES),
                             status=400, code='invalid_roles')
        minutes, error = parse_int(payload.get('session_minutes', 15), 'session_minutes')
        if error:
            return error
        if not 1 <= minutes <= 480:
            return api_error('session_minutes must be between 1 and 480.', status=400, code='invalid_session_minutes')
        vals = {'allow_%s' % role: role in roles for role in KIOSK_ROLES}
        vals.update(name=name, session_minutes=minutes, company_id=request.env.user.company_id.id,
                    created_by_id=request.env.user.id)
        kiosk, raw_key = request.env['bxi.face.kiosk'].sudo()._create_with_key(vals)
        return api_response(dict(_kiosk_dict(kiosk), key=raw_key))

    @http.route('/api/v1/admin/face/kiosks/<int:kiosk_id>/revoke', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @manager_only
    def revoke_kiosk(self, kiosk_id, **kwargs):
        kiosk = request.env['bxi.face.kiosk'].sudo().with_context(active_test=False).browse(kiosk_id)
        if not kiosk.exists() or kiosk.company_id not in _companies():
            return api_error('Kiosk not found.', status=404, code='not_found')
        kiosk.active = False
        # Sessions opened on the kiosk end with it.
        request.env['bxi.api.token'].sudo().search([
            ('face_kiosk_id', '=', kiosk.id), ('active', '=', True),
        ]).action_revoke()
        return api_response(_kiosk_dict(kiosk))

    # -- settings ----------------------------------------------------------------------------

    @http.route('/api/v1/admin/face/settings', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    @manager_only
    def get_settings(self, **kwargs):
        return api_response(_settings_dict(request.env.user.company_id.sudo()))

    @http.route('/api/v1/admin/face/settings', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @manager_only
    def update_settings(self, **kwargs):
        """Change any subset of the settings returned by GET."""
        payload, _files, error = read_payload()
        if error:
            return error
        unknown = sorted(set(payload) - set(SETTINGS))
        if unknown:
            return api_error('Unknown setting(s): %s.' % ', '.join(unknown), status=400, code='invalid_setting')
        vals = {}
        for name, value in payload.items():
            field, kind, low, high = SETTINGS[name]
            if kind == 'bool':
                if not isinstance(value, bool):
                    return api_error('%s must be true or false.' % name, status=400, code='invalid_%s' % name)
            elif kind in ('float', 'int'):
                if isinstance(value, bool) or not isinstance(value, (int, float)) \
                        or (kind == 'int' and int(value) != value) or not low <= value <= high:
                    return api_error('%s must be a number between %s and %s.' % (name, low, high),
                                     status=400, code='invalid_%s' % name)
                value = int(value) if kind == 'int' else float(value)
            elif kind == 'ids':
                ids, error = parse_ids(value, name)
                if error:
                    return error
                courses = request.env['op.course'].sudo().browse(ids).exists()
                if len(courses) != len(set(ids)):
                    return api_error('Unknown class id in %s.' % name, status=400, code='invalid_%s' % name)
                value = [(6, 0, courses.ids)]
            elif kind == 'char':
                if not isinstance(value, str) or not value.strip():
                    return api_error('%s must be text.' % name, status=400, code='invalid_%s' % name)
                value = value.strip()
            vals[field] = value
        company = request.env.user.company_id.sudo()
        company.write(vals)
        return api_response(_settings_dict(company))
