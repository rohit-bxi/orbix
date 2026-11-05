# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

import base64
import binascii

import numpy as np

from odoo import fields
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error

from ..lib.engine import FaceError
from ..lib.matching import CENTER_MAX_YAW, SAME_PERSON_MIN
from ..models.face_service import FaceEngineUnavailable

MAX_FRAME_BYTES = 5 * 1024 * 1024
ENROL_MIN_FRAMES = 3
ENROL_MAX_FRAMES = 5
ACTIONS = ('center', 'left', 'right')


def face_error(message, status, code, **extra):
    """The standard error envelope, plus optional detail such as which
    photo (`frame`, `action`) was the problem."""
    error = {'message': message, 'code': code}
    error.update({key: value for key, value in extra.items() if value is not None})
    return request.make_json_response({'success': False, 'error': error}, status=status)


def engine_unavailable():
    return api_error('Face login is temporarily unavailable. Use your password or OTP.',
                     status=503, code='face_engine_unavailable')


def dt(value):
    return fields.Datetime.to_string(value) if value else None


def read_payload():
    """(payload, files, error). Accepts a JSON body, or multipart/form-data
    whose form fields become the payload and whose file parts become
    (field_name, bytes) pairs."""
    httprequest = request.httprequest
    if httprequest.mimetype == 'multipart/form-data':
        files = [(key, storage.read()) for key, storage in httprequest.files.items(multi=True)]
        return httprequest.form.to_dict(), files, None
    try:
        payload = request.get_json_data() if httprequest.get_data() else {}
    except ValueError:
        return {}, [], api_error('The request body must be JSON.', status=400, code='invalid_json')
    if not isinstance(payload, dict):
        return {}, [], api_error('The request body must be a JSON object.', status=400, code='invalid_json')
    return payload, [], None


def _decode_image(value):
    if not isinstance(value, str) or not value:
        return None
    if value.startswith('data:') and ';base64,' in value:
        value = value.split(';base64,', 1)[1]
    try:
        return base64.b64decode(''.join(value.split()), validate=True)
    except (binascii.Error, ValueError):
        return None


def read_frames(payload, files, min_count, max_count):
    """([(action_or_None, bytes), ...], error).

    JSON: "frames": [{"action": "center", "image": "<base64>"}, ...]
    (a bare base64 string per frame is accepted too). Multipart: one file
    part per photo, named after its action (center/left/right) for login,
    or anything (e.g. "frames") for enrolment.
    """
    frames = []
    if files:
        for key, content in files:
            frames.append((key if key in ACTIONS else None, content))
    else:
        raw = payload.get('frames')
        if not isinstance(raw, list) or not raw:
            return None, api_error('frames is required: a list of photos.', status=400, code='missing_frames')
        for index, entry in enumerate(raw):
            if isinstance(entry, dict):
                action, image = entry.get('action'), entry.get('image')
            else:
                action, image = None, entry
            data = _decode_image(image)
            if not data:
                return None, face_error('Photo %s is not valid base64 image data.' % (index + 1),
                                        400, 'invalid_image', frame=index)
            frames.append((action if action in ACTIONS else None, data))
    if not min_count <= len(frames) <= max_count:
        if min_count == max_count:
            message = 'Send exactly %s photos.' % min_count
        else:
            message = 'Send between %s and %s photos.' % (min_count, max_count)
        return None, api_error(message, status=400, code='invalid_frames')
    for index, (_action, content) in enumerate(frames):
        if len(content) > MAX_FRAME_BYTES:
            return None, face_error('Each photo must be 5 MB or smaller.', 413, 'file_too_large', frame=index)
    return frames, None


def analyze_enrolment_frames(frames):
    """Run the engine on enrolment photos and check they are usable
    together. Returns (analyses, actions, error)."""
    Service = request.env['bxi.face.service']
    try:
        engine = Service._get_engine()
    except FaceEngineUnavailable:
        return None, None, engine_unavailable()
    analyses = []
    for index, (_action, content) in enumerate(frames):
        try:
            analyses.append(engine.analyze(content))
        except FaceError as exc:
            return None, None, face_error(exc.message, 400, exc.code, frame=index)
    frontal = min(analyses, key=lambda analysis: abs(analysis.yaw))
    if abs(frontal.yaw) > CENTER_MAX_YAW:
        return None, None, api_error(
            'At least one photo must look straight at the camera.', status=400, code='no_frontal_face')
    for index, analysis in enumerate(analyses):
        if float(np.dot(analysis.embedding, frontal.embedding)) < SAME_PERSON_MIN:
            return None, None, face_error(
                'The photos are not all of the same person.', 400, 'inconsistent_faces', frame=index)
    return analyses, [action for action, _content in frames], None


def is_face_manager(user):
    return user.has_group('base.group_system') or user.has_group('bxi_face_auth.group_face_manager')


def person(user):
    return {'id': user.id, 'name': user.name, 'login': user.login} if user else None


def consent_dict(student):
    consent = request.env['bxi.face.service']._active_consent(student)
    if not consent:
        return {'granted': False}
    return {
        'granted': True,
        'granted_at': dt(consent.granted_at),
        'granted_by': person(consent.granted_by_id),
        'method': consent.method,
        'version': consent.consent_version or None,
    }


def face_status(user):
    """Face-login state of an account, as shown to the person (or parent)."""
    Service = request.env['bxi.face.service']
    if not user:
        return {'state': 'none', 'can_use_face_login': False, 'unavailable_reason': 'no_account'}
    Enrolment = request.env['bxi.face.enrolment'].sudo()
    active = Enrolment.search([('user_id', '=', user.id), ('state', '=', 'active')], limit=1)
    pending = Enrolment.search([('user_id', '=', user.id), ('state', '=', 'pending')], limit=1)
    latest = Enrolment.search([('user_id', '=', user.id)], limit=1)
    ok, reason = Service._eligibility(user)
    status = {
        'state': 'none',
        'can_use_face_login': bool(ok and active),
        'unavailable_reason': reason if not ok else (None if active else 'not_enrolled'),
        'enrolled_at': None,
        'expires_at': None,
        'pending_since': dt(pending.create_date) if pending else None,
        'reject_reason': None,
    }
    if active:
        status.update(state='active', enrolled_at=dt(active.activated_at), expires_at=dt(active.expires_at))
    elif pending:
        status['state'] = 'pending'
    elif latest.state == 'rejected':
        status.update(state='rejected', reject_reason=latest.reject_reason or None)
    elif latest.state == 'expired' and latest.end_reason == 'validity period ended':
        status['state'] = 'expired'
    return status


def _student_dict(student):
    running = student.course_detail_ids.filtered(lambda line: line.state == 'running')[:1]
    return {
        'id': student.id,
        'name': student.name,
        'gr_no': student.gr_no or None,
        'class': {'id': running.course_id.id, 'name': running.course_id.name} if running.course_id else None,
        'section': {'id': running.batch_id.id, 'name': running.batch_id.name} if running.batch_id else None,
    }


def identity(user, allowed_roles=None):
    """Who a recognised face belongs to, in school terms: `role` is the
    person's main role (student, teacher, parent or staff - the first one
    face login is allowed for, in that order), `roles` all of them, plus the
    matching school record(s). A teacher who is also a parent on the same
    account gets role 'teacher' and both records."""
    Service = request.env['bxi.face.service']
    user = user.sudo()
    roles = Service._eligible_roles(user, allowed_roles)[0]
    student, faculty, parent = Service._school_records(user)
    return {
        'user_id': user.id,
        'name': user.name,
        'role': roles[0] if roles else None,
        'roles': roles,
        'student': _student_dict(student) if student and 'student' in roles else None,
        'teacher': {'id': faculty.id, 'name': faculty.name} if faculty and 'teacher' in roles else None,
        'parent': {
            'id': parent.id,
            'name': parent.name.name,
            'children': [_student_dict(child) for child in parent.student_ids],
        } if parent and 'parent' in roles else None,
    }


def account_summary(user, allowed_roles=None):
    """One choice in a `selection_required` answer: the identity block
    (user_id, name, role, roles, records)."""
    return identity(user, allowed_roles)


def notify(users, title, body, category='face_login', record=None):
    request.env['bxi.notification'].sudo()._notify(users, title, body, category=category, record=record)
