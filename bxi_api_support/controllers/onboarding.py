# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import parse_pagination

ADMIN_GROUP = 'openeducat_core.group_op_back_office_admin'
FACULTY_GROUP = 'openeducat_core.group_op_faculty'

UPDATE_FIELDS = (
    'full_name', 'gender', 'birth_date', 'email', 'phone', 'blood_group', 'nationality',
    'street', 'street2', 'city', 'state_id', 'zip', 'country_id',
    'admission_number', 'admission_date', 'course_id', 'batch_id', 'roll_number',
    'enrollment_status', 'parent_id',
)


def _is_onboarding_admin(user):
    return user.has_group(ADMIN_GROUP)


def _can_manage_onboarding(user):
    return _is_onboarding_admin(user) or user.has_group(FACULTY_GROUP)


def _onboarding_dict(record):
    return {
        'id': record.id,
        'state': record.state,
        'full_name': record.full_name,
        'gender': record.gender,
        'birth_date': record.birth_date and record.birth_date.isoformat(),
        'email': record.email,
        'phone': record.phone,
        'admission_number': record.admission_number,
        'course': record.course_id.display_name,
        'batch': record.batch_id.display_name,
        'roll_number': record.roll_number,
        'enrollment_status': record.enrollment_status,
        'parent': record.parent_id.display_name,
        'student_id': record.student_id.id or None,
    }


class BxiApiSupportOnboardingController(http.Controller):

    @http.route('/api/v1/onboarding', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_onboarding(self, **kwargs):
        user = request.env.user
        if not _can_manage_onboarding(user):
            return api_error('Not authorized to view onboarding records.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [] if _is_onboarding_admin(user) else [('create_uid', '=', user.id)]
        Onboarding = request.env['bxi.student.onboarding'].sudo()
        total = Onboarding.search_count(domain)
        records = Onboarding.search(domain, limit=limit, offset=offset, order='id desc')
        return api_response(
            {'onboarding': [_onboarding_dict(r) for r in records]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/onboarding/<int:onboarding_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_onboarding(self, onboarding_id, **kwargs):
        record, error = self._authorized(onboarding_id)
        if error:
            return error
        return api_response(_onboarding_dict(record))

    @http.route('/api/v1/onboarding', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_onboarding(self, **kwargs):
        if not _can_manage_onboarding(request.env.user):
            return api_error('Not authorized to start onboarding.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        vals = {key: payload[key] for key in UPDATE_FIELDS if key in payload}
        record = request.env['bxi.student.onboarding'].sudo().create(vals)
        return api_response(_onboarding_dict(record), status=201)

    @http.route('/api/v1/onboarding/<int:onboarding_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_onboarding(self, onboarding_id, **kwargs):
        record, error = self._authorized(onboarding_id)
        if error:
            return error
        payload = request.get_json_data() or {}
        vals = {key: payload[key] for key in UPDATE_FIELDS if key in payload}
        record.write(vals)
        return api_response(_onboarding_dict(record))

    @http.route('/api/v1/onboarding/<int:onboarding_id>/next', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def next_step(self, onboarding_id, **kwargs):
        record, error = self._authorized(onboarding_id)
        if error:
            return error
        _, error = call_action(record, 'action_next')
        if error:
            return error
        return api_response(_onboarding_dict(record))

    @http.route('/api/v1/onboarding/<int:onboarding_id>/back', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def back_step(self, onboarding_id, **kwargs):
        record, error = self._authorized(onboarding_id)
        if error:
            return error
        _, error = call_action(record, 'action_back')
        if error:
            return error
        return api_response(_onboarding_dict(record))

    @http.route('/api/v1/onboarding/<int:onboarding_id>/complete', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def complete_onboarding(self, onboarding_id, **kwargs):
        record, error = self._authorized(onboarding_id)
        if error:
            return error
        if record.state != 'documents':
            return api_error(
                'Onboarding must reach the Documents step before it can be completed.',
                status=400, code='invalid_transition')
        _, error = call_action(record, 'action_complete_onboarding')
        if error:
            return error
        return api_response(_onboarding_dict(record))

    def _authorized(self, onboarding_id):
        user = request.env.user
        if not _can_manage_onboarding(user):
            return None, api_error('Not authorized for onboarding records.', status=403, code='forbidden')
        record = request.env['bxi.student.onboarding'].sudo().browse(onboarding_id)
        if not record.exists():
            return None, api_error('Onboarding record not found.', status=404, code='not_found')
        if not _is_onboarding_admin(user) and record.create_uid.id != user.id:
            return None, api_error('Not authorized for this onboarding record.', status=403, code='forbidden')
        return record, None
