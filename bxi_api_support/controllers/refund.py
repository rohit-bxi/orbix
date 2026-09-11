# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import get_authorized_student, get_own_student_ids, parse_pagination, safe_create

REFUND_STAFF_GROUP = 'bxi_student_refund_management.group_refund_staff'

CREATE_FIELDS = (
    'refund_type', 'refund_amount', 'original_payment_mode', 'transaction_reference',
    'reason', 'additional_notes', 'preferred_refund_mode', 'account_holder_name',
    'bank_account_number', 'ifsc_code', 'bank_name', 'branch_name',
)


def _is_refund_staff(user):
    return user.has_group(REFUND_STAFF_GROUP)


def _refund_dict(refund):
    return {
        'id': refund.id,
        'name': refund.name,
        'student_id': refund.student_id.id,
        'refund_type': refund.refund_type,
        'refund_amount': refund.refund_amount,
        'reason': refund.reason,
        'total_fee_amount': refund.total_fee_amount,
        'total_paid_amount': refund.total_paid_amount,
        'excess_amount': refund.excess_amount,
        'pending_amount': refund.pending_amount,
        'status': refund.status,
        'priority': refund.priority,
        'days_pending': refund.days_pending,
        'approved_by': refund.approved_by.name or None,
        'approval_date': refund.approval_date and refund.approval_date.isoformat(),
        'refund_utr': refund.refund_utr,
        'refund_completion_date': refund.refund_completion_date and refund.refund_completion_date.isoformat(),
        'payment_id': refund.payment_id.id or None,
    }


class BxiApiSupportRefundController(http.Controller):

    @http.route('/api/v1/refunds', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_refunds(self, **kwargs):
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [] if _is_refund_staff(request.env.user) else [
            ('student_id', 'in', get_own_student_ids(request.env))]
        Refund = request.env['bxi.student.refund.request'].sudo()
        total = Refund.search_count(domain)
        refunds = Refund.search(domain, limit=limit, offset=offset, order='request_date desc')
        return api_response(
            {'refunds': [_refund_dict(r) for r in refunds]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/refunds/<int:refund_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_refund(self, refund_id, **kwargs):
        refund = request.env['bxi.student.refund.request'].sudo().browse(refund_id)
        if not refund.exists():
            return api_error('Refund request not found.', status=404, code='not_found')
        if not _is_refund_staff(request.env.user) and refund.student_id.id not in get_own_student_ids(request.env):
            return api_error('Not authorized for this refund request.', status=403, code='forbidden')
        return api_response(_refund_dict(refund))

    @http.route('/api/v1/refunds', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_refund(self, **kwargs):
        payload = request.get_json_data() or {}
        student, error = get_authorized_student(payload.get('student_id'), is_staff=_is_refund_staff)
        if error:
            return error
        if not payload.get('refund_type'):
            return api_error('refund_type is required.', status=400, code='missing_refund_type')
        if payload.get('refund_amount') is None:
            return api_error('refund_amount is required.', status=400, code='missing_refund_amount')
        if not payload.get('reason'):
            return api_error('reason is required.', status=400, code='missing_reason')

        vals = {key: payload[key] for key in CREATE_FIELDS if key in payload}
        vals['student_id'] = student.id
        refund, error = safe_create(request.env['bxi.student.refund.request'].sudo(), vals)
        if error:
            return error
        return api_response(_refund_dict(refund), status=201)

    @http.route('/api/v1/refunds/<int:refund_id>/submit', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def submit_refund(self, refund_id, **kwargs):
        return self._transition(refund_id, 'action_submit', require_staff=False)

    @http.route('/api/v1/refunds/<int:refund_id>/start-review', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def start_review_refund(self, refund_id, **kwargs):
        return self._transition(refund_id, 'action_start_review', require_staff=True)

    @http.route('/api/v1/refunds/<int:refund_id>/approve', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def approve_refund(self, refund_id, **kwargs):
        return self._transition(refund_id, 'action_approve', require_staff=True)

    @http.route('/api/v1/refunds/<int:refund_id>/reject', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reject_refund(self, refund_id, **kwargs):
        return self._transition(refund_id, 'action_reject', require_staff=True)

    @http.route('/api/v1/refunds/<int:refund_id>/start-processing', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def start_processing_refund(self, refund_id, **kwargs):
        return self._transition(refund_id, 'action_start_processing', require_staff=True)

    @http.route('/api/v1/refunds/<int:refund_id>/approve-and-process', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def approve_and_process_refund(self, refund_id, **kwargs):
        return self._transition(refund_id, 'action_approve_and_process', require_staff=True)

    @http.route('/api/v1/refunds/<int:refund_id>/reset', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reset_refund(self, refund_id, **kwargs):
        return self._transition(refund_id, 'action_reset_to_draft', require_staff=True)

    @http.route('/api/v1/refunds/<int:refund_id>/complete', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def complete_refund(self, refund_id, **kwargs):
        if not _is_refund_staff(request.env.user):
            return api_error('Not authorized for this action.', status=403, code='forbidden')
        refund = request.env['bxi.student.refund.request'].sudo().browse(refund_id)
        if not refund.exists():
            return api_error('Refund request not found.', status=404, code='not_found')

        payload = request.get_json_data() or {}
        refund_utr = payload.get('refund_utr')
        if refund_utr:
            refund.refund_utr = refund_utr
        if payload.get('refund_confirmation_notes'):
            refund.refund_confirmation_notes = payload['refund_confirmation_notes']

        _, error = call_action(refund, 'action_complete')
        if error:
            return error
        return api_response(_refund_dict(refund))

    def _transition(self, refund_id, method_name, require_staff):
        refund = request.env['bxi.student.refund.request'].sudo().browse(refund_id)
        if not refund.exists():
            return api_error('Refund request not found.', status=404, code='not_found')
        if require_staff:
            if not _is_refund_staff(request.env.user):
                return api_error('Not authorized for this action.', status=403, code='forbidden')
        elif not _is_refund_staff(request.env.user) and refund.student_id.id not in get_own_student_ids(request.env):
            return api_error('Not authorized for this refund request.', status=403, code='forbidden')
        _, error = call_action(refund, method_name)
        if error:
            return error
        return api_response(_refund_dict(refund))
