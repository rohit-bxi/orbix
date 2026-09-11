# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import get_authorized_student, get_own_student_ids, parse_pagination, safe_create

EXEMPTION_STAFF_GROUP = 'bxi_fee_exemption_management.group_exemption_staff'

REQUEST_CREATE_FIELDS = (
    'exemption_type', 'request_value_type', 'requested_amount', 'requested_percentage',
    'reason', 'additional_notes', 'academic_performance', 'attendance_percentage',
    'family_income', 'sibling_count',
)
APPROVE_WIZARD_FIELDS = (
    'approval_type', 'exemption_method', 'approved_amount', 'fee_category_scope',
    'priority_level', 'valid_from', 'valid_until', 'auto_renew', 'approval_notes',
    'internal_remarks', 'notify_parent', 'notify_sms', 'notify_update_portal',
    'notify_auto_adjust_pending',
)
REJECT_WIZARD_FIELDS = (
    'rejection_reason_category', 'detailed_rejection_reason', 'reapplication_suggestions',
    'allow_reapplication', 'internal_notes', 'notify_parent', 'notify_sms', 'notify_update_portal',
)


def _is_exemption_staff(user):
    return user.has_group(EXEMPTION_STAFF_GROUP)


def _build_vals(payload, allowed_fields, extra=None):
    vals = {key: payload[key] for key in allowed_fields if key in payload}
    if 'applicable_fee_category_ids' in payload:
        vals['applicable_fee_category_ids'] = [(6, 0, payload['applicable_fee_category_ids'])]
    if extra:
        vals.update(extra)
    return vals


def _request_dict(req):
    return {
        'id': req.id,
        'name': req.name,
        'student_id': req.student_id.id,
        'class': req.class_id.display_name,
        'section': req.section_id.display_name,
        'exemption_type': req.exemption_type,
        'request_value_type': req.request_value_type,
        'requested_amount': req.requested_amount,
        'requested_percentage': req.requested_percentage,
        'reason': req.reason,
        'total_fee_amount': req.total_fee_amount,
        'total_paid_amount': req.total_paid_amount,
        'pending_amount': req.pending_amount,
        'status': req.status,
        'exemption_id': req.exemption_id.id or None,
        'approved_by': req.approved_by.name or None,
        'approval_date': req.approval_date and req.approval_date.isoformat(),
        'rejection_reason_category': req.rejection_reason_category,
        'rejection_reason': req.rejection_reason,
        'submitted_date': req.submitted_date and req.submitted_date.isoformat(),
    }


def _exemption_dict(exemption):
    return {
        'id': exemption.id,
        'name': exemption.name,
        'student_id': exemption.student_id.id,
        'request_id': exemption.request_id.id or None,
        'exemption_type': exemption.exemption_type,
        'category': exemption.category,
        'exemption_method': exemption.exemption_method,
        'coverage_percentage': exemption.coverage_percentage,
        'fixed_amount': exemption.fixed_amount,
        'total_fee_amount': exemption.total_fee_amount,
        'exemption_amount': exemption.exemption_amount,
        'net_payable_amount': exemption.net_payable_amount,
        'valid_from': exemption.valid_from and exemption.valid_from.isoformat(),
        'valid_until': exemption.valid_until and exemption.valid_until.isoformat(),
        'approval_status': exemption.approval_status,
        'approved_by': exemption.approved_by.name or None,
        'approval_date': exemption.approval_date and exemption.approval_date.isoformat(),
    }


class BxiApiSupportFeeExemptionController(http.Controller):

    # -- Exemption requests (family-submitted) -----------------------------

    @http.route('/api/v1/fee-exemptions/requests', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_requests(self, **kwargs):
        user = request.env.user
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [] if _is_exemption_staff(user) else [('student_id', 'in', get_own_student_ids(request.env))]
        Request = request.env['bxi.fee.exemption.request'].sudo()
        total = Request.search_count(domain)
        requests = Request.search(domain, limit=limit, offset=offset, order='submitted_date desc')
        return api_response(
            {'requests': [_request_dict(r) for r in requests]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/fee-exemptions/requests/<int:request_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_request(self, request_id, **kwargs):
        req = request.env['bxi.fee.exemption.request'].sudo().browse(request_id)
        if not req.exists():
            return api_error('Exemption request not found.', status=404, code='not_found')
        if not _is_exemption_staff(request.env.user) and req.student_id.id not in get_own_student_ids(request.env):
            return api_error('Not authorized for this request.', status=403, code='forbidden')
        return api_response(_request_dict(req))

    @http.route('/api/v1/fee-exemptions/requests', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_request(self, **kwargs):
        payload = request.get_json_data() or {}
        student, error = get_authorized_student(payload.get('student_id'), is_staff=_is_exemption_staff)
        if error:
            return error
        if not payload.get('exemption_type'):
            return api_error('exemption_type is required.', status=400, code='missing_exemption_type')
        if not payload.get('reason'):
            return api_error('reason is required.', status=400, code='missing_reason')
        vals = _build_vals(payload, REQUEST_CREATE_FIELDS, extra={'student_id': student.id})
        req, error = safe_create(request.env['bxi.fee.exemption.request'].sudo(), vals)
        if error:
            return error
        return api_response(_request_dict(req), status=201)

    @http.route('/api/v1/fee-exemptions/requests/<int:request_id>/submit', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def submit_request(self, request_id, **kwargs):
        return self._transition_request(request_id, 'action_submit', require_staff=False)

    @http.route('/api/v1/fee-exemptions/requests/<int:request_id>/start-review', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def start_review_request(self, request_id, **kwargs):
        return self._transition_request(request_id, 'action_start_review', require_staff=True)

    @http.route('/api/v1/fee-exemptions/requests/<int:request_id>/reset', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reset_request(self, request_id, **kwargs):
        return self._transition_request(request_id, 'action_reset_to_draft', require_staff=True)

    def _transition_request(self, request_id, method_name, require_staff):
        req = request.env['bxi.fee.exemption.request'].sudo().browse(request_id)
        if not req.exists():
            return api_error('Exemption request not found.', status=404, code='not_found')
        if require_staff:
            if not _is_exemption_staff(request.env.user):
                return api_error('Not authorized for this action.', status=403, code='forbidden')
        elif not _is_exemption_staff(request.env.user) and req.student_id.id not in get_own_student_ids(request.env):
            return api_error('Not authorized for this request.', status=403, code='forbidden')
        _, error = call_action(req, method_name)
        if error:
            return error
        return api_response(_request_dict(req))

    @http.route('/api/v1/fee-exemptions/requests/<int:request_id>/approve', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def approve_request(self, request_id, **kwargs):
        if not _is_exemption_staff(request.env.user):
            return api_error('Not authorized to approve exemption requests.', status=403, code='forbidden')
        req = request.env['bxi.fee.exemption.request'].sudo().browse(request_id)
        if not req.exists():
            return api_error('Exemption request not found.', status=404, code='not_found')

        # Reuses the same allowed-status check the backend "Approve" button
        # runs (action_open_approve_wizard), instead of duplicating it here.
        _, error = call_action(req, 'action_open_approve_wizard')
        if error:
            return error

        payload = request.get_json_data() or {}
        if payload.get('approved_amount') is None:
            return api_error('approved_amount is required.', status=400, code='missing_approved_amount')
        if not payload.get('valid_until'):
            return api_error('valid_until is required.', status=400, code='missing_valid_until')

        vals = _build_vals(payload, APPROVE_WIZARD_FIELDS, extra={'request_id': req.id})
        wizard, error = safe_create(request.env['bxi.fee.exemption.approve.wizard'].sudo(), vals)
        if error:
            return error
        _, error = call_action(wizard, 'action_confirm_approve')
        if error:
            return error
        return api_response(_request_dict(req))

    @http.route('/api/v1/fee-exemptions/requests/<int:request_id>/reject', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reject_request(self, request_id, **kwargs):
        if not _is_exemption_staff(request.env.user):
            return api_error('Not authorized to reject exemption requests.', status=403, code='forbidden')
        req = request.env['bxi.fee.exemption.request'].sudo().browse(request_id)
        if not req.exists():
            return api_error('Exemption request not found.', status=404, code='not_found')

        _, error = call_action(req, 'action_open_reject_wizard')
        if error:
            return error

        payload = request.get_json_data() or {}
        if not payload.get('rejection_reason_category'):
            return api_error('rejection_reason_category is required.', status=400, code='missing_rejection_reason_category')
        if not payload.get('detailed_rejection_reason'):
            return api_error('detailed_rejection_reason is required.', status=400, code='missing_detailed_rejection_reason')

        vals = _build_vals(payload, REJECT_WIZARD_FIELDS, extra={
            'request_id': req.id,
            # The "type REJECT to confirm" field only guards against a slip
            # of the mouse in the backend form - an authenticated, role-gated
            # API call is not that kind of accident, so it is set here rather
            # than asked of the caller.
            'confirmation_text': 'REJECT',
        })
        wizard = request.env['bxi.fee.exemption.reject.wizard'].sudo().create(vals)
        _, error = call_action(wizard, 'action_confirm_reject')
        if error:
            return error
        return api_response(_request_dict(req))

    # -- Exemptions (staff-granted directly, or created from an approved request) --

    @http.route('/api/v1/fee-exemptions', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_exemptions(self, **kwargs):
        user = request.env.user
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [] if _is_exemption_staff(user) else [('student_id', 'in', get_own_student_ids(request.env))]
        Exemption = request.env['bxi.fee.exemption'].sudo()
        total = Exemption.search_count(domain)
        exemptions = Exemption.search(domain, limit=limit, offset=offset, order='valid_from desc')
        return api_response(
            {'exemptions': [_exemption_dict(e) for e in exemptions]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/fee-exemptions/<int:exemption_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_exemption(self, exemption_id, **kwargs):
        exemption = request.env['bxi.fee.exemption'].sudo().browse(exemption_id)
        if not exemption.exists():
            return api_error('Fee exemption not found.', status=404, code='not_found')
        if not _is_exemption_staff(request.env.user) and exemption.student_id.id not in get_own_student_ids(request.env):
            return api_error('Not authorized for this exemption.', status=403, code='forbidden')
        return api_response(_exemption_dict(exemption))

    @http.route('/api/v1/fee-exemptions/<int:exemption_id>/submit', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def submit_exemption(self, exemption_id, **kwargs):
        return self._transition_exemption(exemption_id, 'action_submit')

    @http.route('/api/v1/fee-exemptions/<int:exemption_id>/approve', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def approve_exemption(self, exemption_id, **kwargs):
        return self._transition_exemption(exemption_id, 'action_approve')

    @http.route('/api/v1/fee-exemptions/<int:exemption_id>/reject', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reject_exemption(self, exemption_id, **kwargs):
        return self._transition_exemption(exemption_id, 'action_reject')

    @http.route('/api/v1/fee-exemptions/<int:exemption_id>/reset', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reset_exemption(self, exemption_id, **kwargs):
        return self._transition_exemption(exemption_id, 'action_reset_to_draft')

    def _transition_exemption(self, exemption_id, method_name):
        if not _is_exemption_staff(request.env.user):
            return api_error('Not authorized to manage fee exemptions.', status=403, code='forbidden')
        exemption = request.env['bxi.fee.exemption'].sudo().browse(exemption_id)
        if not exemption.exists():
            return api_error('Fee exemption not found.', status=404, code='not_found')
        _, error = call_action(exemption, method_name)
        if error:
            return error
        return api_response(_exemption_dict(exemption))
