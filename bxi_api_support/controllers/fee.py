# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_file_response, api_response, call_action, parse_int, require_auth

from .common import get_authorized_student, parse_ids, parse_pagination, safe_create, user_can_access_student

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

    @http.route('/api/v1/fees/students/<int:student_id>/dues', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def student_dues(self, student_id, **kwargs):
        """What is still owed: every non-cancelled fee line with a pending
        balance, oldest due first, plus the totals the app's fee card shows."""
        student, error = get_authorized_student(student_id, is_staff=_is_fee_staff)
        if error:
            return error
        details = request.env['op.student.fees.details'].sudo().search([
            ('student_id', '=', student.id), ('state', '!=', 'cancel'), ('amount_pending', '>', 0),
        ], order='date asc, id asc')
        overdue = details.filtered(lambda d: d.days_overdue > 0)
        upcoming = details - overdue
        return api_response({
            'total_pending': sum(details.mapped('amount_pending')),
            'overdue_amount': sum(overdue.mapped('amount_pending')),
            'next_due': _detail_dict(upcoming[0]) if upcoming else None,
            'currency': (details[:1].currency_id or request.env.company.currency_id).name,
            'dues': [_detail_dict(d) for d in details],
        })

    @http.route('/api/v1/fees/students/<int:student_id>/receipts', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def student_receipts(self, student_id, **kwargs):
        """Payment history: every inbound payment received from the
        student's account, with the fee lines it settled."""
        student, error = get_authorized_student(student_id, is_staff=_is_fee_staff)
        if error:
            return error
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Payment = request.env['account.payment'].sudo()
        domain = [('partner_id', '=', student.partner_id.id), ('payment_type', '=', 'inbound'),
                  ('state', 'in', ('paid', 'in_process'))]
        total = Payment.search_count(domain)
        payments = Payment.search(domain, limit=limit, offset=offset, order='date desc, id desc')
        Detail = request.env['op.student.fees.details'].sudo()
        return api_response({'receipts': [{
            'id': payment.id,
            'name': payment.name,
            'date': payment.date and payment.date.isoformat(),
            'amount': payment.amount,
            'currency': payment.currency_id.name,
            'journal': payment.journal_id.name,
            'memo': payment.memo or None,
            'state': payment.state,
            'fee_detail_ids': Detail.search([('invoice_id', 'in', payment.reconciled_invoice_ids.ids)]).ids,
        } for payment in payments]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/fees/details/<int:detail_id>/receipt', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def fee_receipt_pdf(self, detail_id, **kwargs):
        """The Fee Receipt PDF (bxi_fee_dashboard's report) for a fee line
        that has received a payment."""
        detail = request.env['op.student.fees.details'].sudo().browse(detail_id)
        if not detail.exists():
            return api_error('Fee line not found.', status=404, code='not_found')
        if not user_can_access_student(request.env, detail.student_id, is_staff=_is_fee_staff):
            return api_error('Not authorized for this fee line.', status=403, code='forbidden')
        if not detail.amount_paid:
            return api_error('Nothing has been paid on this fee line yet.', status=400, code='nothing_paid')
        report = request.env.ref('bxi_fee_dashboard.action_report_fee_receipt', raise_if_not_found=False)
        if not report:
            return api_error('Fee receipts are not set up (install Fees Dashboard).', status=501, code='not_available')
        pdf, _report_type = request.env['ir.actions.report'].sudo()._render_qweb_pdf(report, detail.ids)
        return api_file_response(pdf, f'fee-receipt-{detail.id}.pdf')

    # -- structure authoring (fee office) -------------------------------------

    STRUCTURE_FIELDS = (
        'name', 'code', 'fees_terms', 'installment_type', 'installment_count', 'first_due_date', 'payment_mode_note',
        'grace_period_days', 'late_fee_enabled', 'late_fee_type', 'late_fee_amount', 'late_fee_max_cap',
        'late_fee_apply_after_days', 'discount_enabled', 'discount_type', 'discount_amount',
        'discount_valid_until', 'allow_sibling_discount', 'auto_reminder', 'auto_receipt',
        'allow_partial_payment', 'notify_admin_on_payment', 'internal_notes', 'parent_instructions',
    )

    def _structure_vals(self, payload):
        """(vals, error): plain fields, classes/sections and the fee
        category lines [{category_id, amount, frequency?}], which replace
        the existing ones when given."""
        vals = {k: payload[k] for k in self.STRUCTURE_FIELDS if k in payload}
        if payload.get('academic_year_id'):
            vals['academic_year_id'], error = parse_int(payload['academic_year_id'], 'academic_year_id')
            if error:
                return None, error
        for key, field in (('course_ids', 'course_ids'), ('batch_ids', 'batch_ids')):
            if key in payload:
                ids, error = parse_ids(payload[key] or [], key)
                if error:
                    return None, error
                vals[field] = [(6, 0, ids)]
        if 'category_lines' in payload:
            lines = [(5, 0, 0)]
            for line in payload['category_lines'] or []:
                category_id, error = parse_int((line or {}).get('category_id'), 'category_id')
                if error:
                    return None, error
                values = {'category_id': category_id, 'amount': line.get('amount') or 0.0}
                if line.get('frequency'):
                    values['frequency'] = line['frequency']
                lines.append((0, 0, values))
            vals['category_line_ids'] = lines
        return vals, None

    @http.route('/api/v1/fees/structures', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_structure(self, **kwargs):
        if not _is_fee_staff(request.env.user):
            return api_error('Not authorized to create fee structures.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        for required in ('name', 'code'):
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        vals, error = self._structure_vals(payload)
        if error:
            return error
        structure, error = safe_create(request.env['op.fees.terms'].sudo(), vals)
        if error:
            return error
        return api_response(_structure_dict(structure), status=201)

    @http.route('/api/v1/fees/structures/<int:structure_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_structure(self, structure_id, **kwargs):
        if not _is_fee_staff(request.env.user):
            return api_error('Not authorized to edit fee structures.', status=403, code='forbidden')
        structure = request.env['op.fees.terms'].sudo().browse(structure_id)
        if not structure.exists():
            return api_error('Fee structure not found.', status=404, code='not_found')
        if structure.state != 'draft':
            return api_error('Only a draft fee structure can be edited.', status=400, code='invalid_transition')
        vals, error = self._structure_vals(request.get_json_data() or {})
        if error:
            return error
        _, error = call_action(structure, 'write', vals=vals)
        if error:
            return error
        return api_response(_structure_dict(structure))

    @http.route('/api/v1/fees/structures/<int:structure_id>/generate-installments', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def generate_installments(self, structure_id, **kwargs):
        return self._transition_structure(structure_id, 'action_generate_installments')

    @http.route('/api/v1/fees/structures/<int:structure_id>/duplicate', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def duplicate_structure(self, structure_id, **kwargs):
        if not _is_fee_staff(request.env.user):
            return api_error('Not authorized to duplicate fee structures.', status=403, code='forbidden')
        structure = request.env['op.fees.terms'].sudo().browse(structure_id)
        if not structure.exists():
            return api_error('Fee structure not found.', status=404, code='not_found')
        # action_duplicate names the copy "(Copy)" and resets it to draft.
        action, error = call_action(structure, 'action_duplicate')
        if error:
            return error
        copy = request.env['op.fees.terms'].sudo().browse(action['res_id'])
        return api_response(_structure_dict(copy), status=201)
