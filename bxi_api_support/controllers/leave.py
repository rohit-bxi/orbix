# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Teacher time off (hr_holidays) on the teacher's own hr.employee
(op.faculty.emp_id): balances, requests, cancel, and approve/refuse for
time-off approvers."""
from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, parse_int, require_auth

from .common import date_str, parse_pagination, ref, safe_create, school_context

OPEN_STATES = ('confirm', 'validate1')


def _own_employee(env):
    faculty = school_context(env)['faculty']
    employee = faculty.emp_id or env.user.employee_id
    if not employee:
        return None, api_error('No employee record is linked to this account.', status=403, code='no_employee')
    return employee.sudo(), None


def _leave_dict(leave):
    return {
        'id': leave.id,
        'employee': ref(leave.employee_id),
        'type': ref(leave.holiday_status_id),
        'date_from': date_str(leave.request_date_from),
        'date_to': date_str(leave.request_date_to),
        'number_of_days': leave.number_of_days,
        'description': leave.sudo().private_name or leave.sudo().name or None,
        'state': leave.state,
        'can_cancel': leave.can_cancel,
    }


class BxiApiSupportLeaveController(http.Controller):

    @http.route('/api/v1/leaves/types', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def leave_types(self, **kwargs):
        employee, error = _own_employee(request.env)
        if error:
            return error
        types = request.env['hr.leave.type'].sudo().with_context(employee_id=employee.id).search([
            '|', ('company_id', '=', False), ('company_id', '=', employee.company_id.id),
        ])
        return api_response({'types': [{
            'id': t.id,
            'name': t.name,
            'requires_allocation': t.requires_allocation,
            'request_unit': t.request_unit,
            'allocated': t.max_leaves if t.requires_allocation else None,
            'taken': t.leaves_taken if t.requires_allocation else None,
            'remaining': t.virtual_remaining_leaves if t.requires_allocation else None,
        } for t in types if not t.requires_allocation or t.max_leaves]})

    @http.route('/api/v1/leaves/my', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def my_leaves(self, **kwargs):
        employee, error = _own_employee(request.env)
        if error:
            return error
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Leave = request.env['hr.leave'].sudo()
        domain = [('employee_id', '=', employee.id)]
        total = Leave.search_count(domain)
        leaves = Leave.search(domain, limit=limit, offset=offset, order='request_date_from desc')
        return api_response({'leaves': [_leave_dict(l) for l in leaves]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/leaves', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def request_leave(self, **kwargs):
        """{type_id, date_from, date_to, description?}: a time-off request
        on the caller's own employee, routed to the usual approvers."""
        employee, error = _own_employee(request.env)
        if error:
            return error
        payload = request.get_json_data() or {}
        for required in ('type_id', 'date_from', 'date_to'):
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        type_id, error = parse_int(payload['type_id'], 'type_id')
        if error:
            return error
        leave, error = safe_create(request.env['hr.leave'].sudo(), {
            'employee_id': employee.id,
            'holiday_status_id': type_id,
            'request_date_from': payload['date_from'],
            'request_date_to': payload['date_to'],
            'private_name': payload.get('description') or False,
        })
        if error:
            return error
        return api_response(_leave_dict(leave), status=201)

    @http.route('/api/v1/leaves/<int:leave_id>/cancel', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def cancel_leave(self, leave_id, **kwargs):
        employee, error = _own_employee(request.env)
        if error:
            return error
        leave = request.env['hr.leave'].sudo().browse(leave_id)
        if not leave.exists() or leave.employee_id != employee:
            return api_error('Time off not found.', status=404, code='not_found')
        reason = (request.get_json_data() or {}).get('reason') if request.httprequest.get_data() else None
        _, error = call_action(leave, '_action_user_cancel', reason=reason or 'Cancelled from the Orbix app')
        if error:
            return error
        return api_response(_leave_dict(leave))

    @http.route('/api/v1/leaves/to-approve', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def to_approve(self, **kwargs):
        """Requests the caller can act on - read with the caller's own
        rights, so a teacher who isn't an approver sees none."""
        try:
            leaves = request.env['hr.leave'].search([('state', 'in', OPEN_STATES)], order='request_date_from')
        except AccessError:
            return api_response({'leaves': []})
        return api_response({'leaves': [
            _leave_dict(l) for l in leaves if l.can_approve or l.can_validate
        ]})

    @http.route('/api/v1/leaves/<int:leave_id>/<any("approve", "refuse"):action>',
                type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def review_leave(self, leave_id, action, **kwargs):
        """Runs as the caller (not sudo): Odoo's own approver rules decide."""
        leave = request.env['hr.leave'].browse(leave_id)
        try:
            if not leave.exists():
                return api_error('Time off not found.', status=404, code='not_found')
            if leave.state not in OPEN_STATES:
                return api_error('This request is not awaiting approval.', status=400, code='invalid_transition')
        except AccessError:
            return api_error('Not authorized for this request.', status=403, code='forbidden')
        _, error = call_action(leave, 'action_approve' if action == 'approve' else 'action_refuse')
        if error:
            return error
        return api_response(_leave_dict(leave.sudo()))
