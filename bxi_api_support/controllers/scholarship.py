# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import get_authorized_student, get_own_student_ids, parse_pagination, safe_create

SCHOLARSHIP_STAFF_GROUP = 'bxi_school_scholarship.group_scholarship_staff'

CREATE_FIELDS = (
    'program_id', 'scholarship_type', 'academic_year_id', 'reason', 'coverage_type',
    'coverage_percentage', 'fixed_amount', 'max_amount_limit', 'fee_category_scope',
    'priority_level', 'valid_from', 'valid_until', 'auto_renew',
)


def _is_scholarship_staff(user):
    return user.has_group(SCHOLARSHIP_STAFF_GROUP)


def _scholarship_dict(scholarship):
    return {
        'id': scholarship.id,
        'name': scholarship.name,
        'student_id': scholarship.student_id.id,
        'program': scholarship.program_id.display_name,
        'scholarship_type': scholarship.scholarship_type,
        'coverage_type': scholarship.coverage_type,
        'coverage_percentage': scholarship.coverage_percentage,
        'fixed_amount': scholarship.fixed_amount,
        'total_fee_amount': scholarship.total_fee_amount,
        'scholarship_amount': scholarship.scholarship_amount,
        'net_payable_amount': scholarship.net_payable_amount,
        'valid_from': scholarship.valid_from and scholarship.valid_from.isoformat(),
        'valid_until': scholarship.valid_until and scholarship.valid_until.isoformat(),
        'approval_status': scholarship.approval_status,
        'approved_by': scholarship.approved_by.name or None,
        'approval_date': scholarship.approval_date and scholarship.approval_date.isoformat(),
    }


class BxiApiSupportScholarshipController(http.Controller):

    @http.route('/api/v1/scholarships', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_scholarships(self, **kwargs):
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [] if _is_scholarship_staff(request.env.user) else [
            ('student_id', 'in', get_own_student_ids(request.env))]
        Scholarship = request.env['bxi.student.scholarship'].sudo()
        total = Scholarship.search_count(domain)
        scholarships = Scholarship.search(domain, limit=limit, offset=offset, order='valid_from desc')
        return api_response(
            {'scholarships': [_scholarship_dict(s) for s in scholarships]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/scholarships/<int:scholarship_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_scholarship(self, scholarship_id, **kwargs):
        scholarship = request.env['bxi.student.scholarship'].sudo().browse(scholarship_id)
        if not scholarship.exists():
            return api_error('Scholarship not found.', status=404, code='not_found')
        if not _is_scholarship_staff(request.env.user) and scholarship.student_id.id not in get_own_student_ids(request.env):
            return api_error('Not authorized for this scholarship.', status=403, code='forbidden')
        return api_response(_scholarship_dict(scholarship))

    @http.route('/api/v1/scholarships', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_scholarship(self, **kwargs):
        if not _is_scholarship_staff(request.env.user):
            return api_error('Not authorized to assign scholarships.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        student, error = get_authorized_student(payload.get('student_id'))
        if error:
            return error
        if not payload.get('academic_year_id'):
            return api_error('academic_year_id is required.', status=400, code='missing_academic_year_id')
        if not payload.get('valid_until'):
            return api_error('valid_until is required.', status=400, code='missing_valid_until')

        vals = {key: payload[key] for key in CREATE_FIELDS if key in payload}
        vals['student_id'] = student.id
        scholarship, error = safe_create(request.env['bxi.student.scholarship'].sudo(), vals)
        if error:
            return error
        return api_response(_scholarship_dict(scholarship), status=201)

    @http.route('/api/v1/scholarships/<int:scholarship_id>/submit', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def submit_scholarship(self, scholarship_id, **kwargs):
        return self._transition(scholarship_id, 'action_submit')

    @http.route('/api/v1/scholarships/<int:scholarship_id>/approve', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def approve_scholarship(self, scholarship_id, **kwargs):
        return self._transition(scholarship_id, 'action_approve')

    @http.route('/api/v1/scholarships/<int:scholarship_id>/reject', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reject_scholarship(self, scholarship_id, **kwargs):
        return self._transition(scholarship_id, 'action_reject')

    @http.route('/api/v1/scholarships/<int:scholarship_id>/reset', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reset_scholarship(self, scholarship_id, **kwargs):
        return self._transition(scholarship_id, 'action_reset_to_draft')

    def _transition(self, scholarship_id, method_name):
        if not _is_scholarship_staff(request.env.user):
            return api_error('Not authorized to manage scholarships.', status=403, code='forbidden')
        scholarship = request.env['bxi.student.scholarship'].sudo().browse(scholarship_id)
        if not scholarship.exists():
            return api_error('Scholarship not found.', status=404, code='not_found')
        _, error = call_action(scholarship, method_name)
        if error:
            return error
        return api_response(_scholarship_dict(scholarship))
