# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, parse_int, require_auth

from .common import get_authorized_student, parse_pagination, user_can_access_student

FEE_STAFF_GROUP = 'openeducat_fees.group_openeducat_fees_user'


def _is_fee_staff(user):
    return user.has_group(FEE_STAFF_GROUP)


def _structure_dict(structure):
    return {
        'id': structure.id,
        'name': structure.name,
        'state': structure.state,
        'academic_year': structure.academic_year_id.display_name,
        'total_amount': structure.total_amount,
        'currency': structure.currency_id.name,
        'installment_type': structure.installment_type,
        'first_due_date': structure.first_due_date and structure.first_due_date.isoformat(),
        'assigned_student_count': structure.assigned_student_count,
        'active_payment_count': structure.active_payment_count,
        'pending_payment_count': structure.pending_payment_count,
    }


def _detail_dict(detail):
    return {
        'id': detail.id,
        'student_id': detail.student_id.id,
        'structure': detail.structure_id.display_name,
        'fee_category': detail.product_id.display_name,
        'due_date': detail.date and detail.date.isoformat(),
        'total_payable': detail.total_payable,
        'amount_paid': detail.amount_paid,
        'amount_pending': detail.amount_pending,
        'late_fee_amount': detail.late_fee_amount,
        'waiver_amount': detail.waiver_amount,
        'days_overdue': detail.days_overdue,
        'collection_status': detail.collection_status,
        'payment_mode': detail.payment_mode,
        'state': detail.state,
        'invoice_id': detail.invoice_id.id or None,
    }


class BxiApiSupportFeeController(http.Controller):

    @http.route('/api/v1/fees/structures', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_structures(self, state=None, **kwargs):
        if not _is_fee_staff(request.env.user):
            return api_error('Not authorized to view fee structures.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [('state', '=', state)] if state else []
        Structure = request.env['op.fees.terms'].sudo()
        total = Structure.search_count(domain)
        structures = Structure.search(domain, limit=limit, offset=offset, order='create_date desc')
        return api_response(
            {'structures': [_structure_dict(s) for s in structures]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/fees/structures/<int:structure_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_structure(self, structure_id, **kwargs):
        if not _is_fee_staff(request.env.user):
            return api_error('Not authorized to view fee structures.', status=403, code='forbidden')
        structure = request.env['op.fees.terms'].sudo().browse(structure_id)
        if not structure.exists():
            return api_error('Fee structure not found.', status=404, code='not_found')
        return api_response(_structure_dict(structure))

    @http.route('/api/v1/fees/structures/<int:structure_id>/activate', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def activate_structure(self, structure_id, **kwargs):
        return self._transition_structure(structure_id, 'action_activate')

    @http.route('/api/v1/fees/structures/<int:structure_id>/deactivate', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def deactivate_structure(self, structure_id, **kwargs):
        if not _is_fee_staff(request.env.user):
            return api_error('Not authorized to manage fee structures.', status=403, code='forbidden')
        structure = request.env['op.fees.terms'].sudo().browse(structure_id)
        if not structure.exists():
            return api_error('Fee structure not found.', status=404, code='not_found')

        payload = request.get_json_data() or {}
        if not (payload.get('ack_impact') and payload.get('ack_reviewed')):
            return api_error(
                'Both ack_impact and ack_reviewed must be true to deactivate a fee structure.',
                status=400, code='missing_acknowledgement')

        wizard = request.env['bxi.fee.structure.deactivate.wizard'].sudo().create({
            'structure_id': structure.id,
            'ack_impact': True,
            'ack_reviewed': True,
        })
        _, error = call_action(wizard, 'action_confirm')
        if error:
            return error
        return api_response(_structure_dict(structure))

    def _transition_structure(self, structure_id, method_name):
        if not _is_fee_staff(request.env.user):
            return api_error('Not authorized to manage fee structures.', status=403, code='forbidden')
        structure = request.env['op.fees.terms'].sudo().browse(structure_id)
        if not structure.exists():
            return api_error('Fee structure not found.', status=404, code='not_found')
        _, error = call_action(structure, method_name)
        if error:
            return error
        return api_response(_structure_dict(structure))

    @http.route('/api/v1/fees/students/<int:student_id>/details', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_student_fee_details(self, student_id, **kwargs):
        student, error = get_authorized_student(student_id, is_staff=_is_fee_staff)
        if error:
            return error
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Detail = request.env['op.student.fees.details'].sudo()
        domain = [('student_id', '=', student.id)]
        total = Detail.search_count(domain)
        details = Detail.search(domain, limit=limit, offset=offset, order='date desc')
        return api_response(
            {'details': [_detail_dict(d) for d in details]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/fees/details/<int:detail_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_fee_detail(self, detail_id, **kwargs):
        detail = request.env['op.student.fees.details'].sudo().browse(detail_id)
        if not detail.exists():
            return api_error('Fee line not found.', status=404, code='not_found')
        if not user_can_access_student(request.env, detail.student_id, is_staff=_is_fee_staff):
            return api_error('Not authorized for this fee line.', status=403, code='forbidden')
        return api_response(_detail_dict(detail))

    @http.route('/api/v1/fees/details/<int:detail_id>/invoice', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_fee_invoice(self, detail_id, **kwargs):
        detail = request.env['op.student.fees.details'].sudo().browse(detail_id)
        if not detail.exists():
            return api_error('Fee line not found.', status=404, code='not_found')
        if not user_can_access_student(request.env, detail.student_id, is_staff=_is_fee_staff):
            return api_error('Not authorized for this fee line.', status=403, code='forbidden')
        detail.get_invoice()
        invoice = detail.invoice_id
        if not invoice:
            return api_error('No invoice could be generated for this fee line.', status=400, code='no_invoice')
        return api_response({
            'id': invoice.id,
            'name': invoice.name,
            'state': invoice.state,
            'amount_total': invoice.amount_total,
            'amount_residual': invoice.amount_residual,
            'payment_state': invoice.payment_state,
        })

    @http.route('/api/v1/fees/details/<int:detail_id>/pay', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def pay_fee_detail(self, detail_id, **kwargs):
        if not _is_fee_staff(request.env.user):
            return api_error('Not authorized to record fee payments.', status=403, code='forbidden')
        detail = request.env['op.student.fees.details'].sudo().browse(detail_id)
        if not detail.exists():
            return api_error('Fee line not found.', status=404, code='not_found')

        payload = request.get_json_data() or {}
        amount = payload.get('amount')
        journal_id = payload.get('journal_id')
        if amount is None:
            return api_error('amount is required.', status=400, code='missing_amount')
        if not journal_id:
            return api_error('journal_id is required.', status=400, code='missing_journal_id')
        journal_id, error = parse_int(journal_id, 'journal_id')
        if error:
            return error
        journal = request.env['account.journal'].sudo().browse(journal_id)
        if not journal.exists():
            return api_error('Journal not found.', status=404, code='not_found')

        wizard_vals = {
            'fees_detail_id': detail.id,
            'amount': amount,
            'journal_id': journal.id,
            'payment_mode': payload.get('payment_mode', 'cash'),
            'reference': payload.get('reference'),
            'memo': payload.get('memo'),
        }
        if payload.get('payment_date'):
            wizard_vals['payment_date'] = payload['payment_date']

        wizard = request.env['bxi.fee.payment.wizard'].sudo().create(wizard_vals)
        _, error = call_action(wizard, 'action_confirm')
        if error:
            return error
        return api_response(_detail_dict(detail))
