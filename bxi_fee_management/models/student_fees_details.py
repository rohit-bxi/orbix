# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import api, fields, models

COLLECTION_STATUSES = [
    ('pending', 'Pending'),
    ('partially_paid', 'Partially Paid'),
    ('paid', 'Paid'),
    ('overdue', 'Overdue'),
]

PAYMENT_MODES = [
    ('cash', 'Cash'),
    ('cheque', 'Cheque'),
    ('bank_transfer', 'Bank Transfer'),
    ('upi', 'UPI'),
    ('card', 'Card'),
    ('online', 'Online Gateway'),
]


class OpStudentFeesDetails(models.Model):
    """Adds the fields the Fee Collection screens need on top of OpenEduCat's
    existing fee-line model. No new ledger model is introduced: paid/pending
    amounts read straight off the linked account.move, and payments are
    recorded through Odoo's own account.payment.register wizard (see
    wizard/fee_payment_wizard.py) rather than a bespoke reconciliation path.
    """
    _name = 'op.student.fees.details'
    _inherit = ['op.student.fees.details', 'mail.thread', 'mail.activity.mixin']

    structure_id = fields.Many2one(
        'op.fees.terms', string='Fee Structure',
        related='fees_line_id.fees_id', store=True, index=True)
    payment_mode = fields.Selection(PAYMENT_MODES, string='Payment Mode', copy=False)

    # OpenEduCat declares currency_id as a non-stored compute. A Monetary
    # field can only offer a pivot/graph "sum" aggregator when its currency
    # field is itself stored (Odoo needs it in the SQL GROUP BY to know
    # which currency each summed total is in) - storing it here is what
    # makes amount_paid/amount_pending usable as pivot measures.
    currency_id = fields.Many2one(store=True)

    amount_paid = fields.Monetary(
        compute='_compute_payment_amounts', store=True, currency_field='currency_id', aggregator='sum')
    late_fee_amount = fields.Monetary(
        compute='_compute_payment_amounts', store=True, currency_field='currency_id', aggregator='sum')
    waiver_ids = fields.One2many('op.student.fee.waiver', 'detail_id', string='Fee Waivers')
    waiver_amount = fields.Monetary(
        compute='_compute_payment_amounts', store=True, currency_field='currency_id', aggregator='sum',
        help='Sum of approved fee-exemption/scholarship waivers applied to this line.')
    total_payable = fields.Monetary(
        compute='_compute_payment_amounts', store=True, currency_field='currency_id', aggregator='sum')
    amount_pending = fields.Monetary(
        compute='_compute_payment_amounts', store=True, currency_field='currency_id', aggregator='sum')
    days_overdue = fields.Integer(compute='_compute_payment_amounts', store=True)
    collection_status = fields.Selection(
        COLLECTION_STATUSES, compute='_compute_payment_amounts', store=True, default='pending')

    @api.depends(
        'after_discount_amount', 'date', 'state', 'waiver_ids.amount',
        'invoice_id.amount_total', 'invoice_id.amount_residual', 'invoice_id.payment_state', 'invoice_id.state',
        'structure_id.grace_period_days', 'structure_id.late_fee_enabled', 'structure_id.late_fee_type',
        'structure_id.late_fee_amount', 'structure_id.late_fee_max_cap', 'structure_id.late_fee_apply_after_days')
    def _compute_payment_amounts(self):
        today = fields.Date.context_today(self)
        for detail in self:
            invoice = detail.invoice_id
            paid = 0.0
            payment_state = False
            invoice_posted = bool(invoice and invoice.state == 'posted')
            if invoice_posted:
                paid = invoice.amount_total - invoice.amount_residual
                payment_state = invoice.payment_state

            days_overdue = 0
            if detail.date and detail.state != 'cancel':
                grace = detail.structure_id.grace_period_days or 0
                overdue_days = (today - detail.date).days - grace
                if overdue_days > 0:
                    days_overdue = overdue_days

            structure = detail.structure_id
            late_fee = 0.0
            if (structure.late_fee_enabled and payment_state not in ('paid', 'in_payment')
                    and days_overdue > (structure.late_fee_apply_after_days or 0)):
                if structure.late_fee_type == 'fixed':
                    late_fee = structure.late_fee_amount
                elif structure.late_fee_type == 'percentage':
                    late_fee = detail.after_discount_amount * structure.late_fee_amount / 100.0
                elif structure.late_fee_type == 'per_day':
                    late_fee = structure.late_fee_amount * days_overdue
                if structure.late_fee_max_cap:
                    late_fee = min(late_fee, structure.late_fee_max_cap)

            waiver = sum(detail.waiver_ids.mapped('amount'))

            if invoice_posted:
                # Once an invoice exists, its amount_total/amount_residual are the
                # accounting source of truth: each fee category line rounds to 2
                # decimals independently, so the invoice total can differ by a
                # cent or two from summing after_discount_amount + late_fee in
                # one shot. Deriving pending straight from amount_residual avoids
                # a payment that exactly covers total_payable getting stuck as
                # "partially paid" over a rounding cent. Waivers approved before
                # the invoice was generated are already folded into it as a
                # dedicated invoice line (see get_invoice()) - a waiver approved
                # after the invoice is posted is not retroactively applied here,
                # the same way a late fee change wouldn't be either.
                total_payable = invoice.amount_total
                pending = invoice.amount_residual
            else:
                total_payable = max(detail.after_discount_amount + late_fee - waiver, 0.0)
                pending = total_payable

            overdue_threshold = structure.late_fee_apply_after_days or 0

            if detail.state == 'cancel':
                status = 'pending'
            elif payment_state in ('paid', 'in_payment'):
                status = 'paid'
            elif payment_state == 'partial':
                status = 'partially_paid'
            elif days_overdue > overdue_threshold:
                status = 'overdue'
            else:
                status = 'pending'

            detail.amount_paid = paid
            detail.late_fee_amount = late_fee
            detail.waiver_amount = waiver
            detail.total_payable = total_payable
            detail.amount_pending = max(pending, 0.0)
            detail.days_overdue = max(days_overdue, 0)
            detail.collection_status = status

    def _cron_recompute_collection_status(self):
        details = self.search([('state', '!=', 'cancel')])
        details._compute_payment_amounts()

    def get_invoice(self):
        """Extends OpenEduCat's invoice creation to add a late fee line when
        one applies, so the invoice total the accounting side sees matches
        total_payable and a full payment reconciles cleanly instead of
        leaving the invoice sitting in a 'partial' state. Also folds in any
        already-approved exemption/scholarship waiver as its own negative
        line, so what gets billed is what's actually owed - a waiver
        approved after this point is not retroactively applied to an
        already-generated invoice.
        """
        res = super().get_invoice()
        for detail in self:
            if not detail.invoice_id:
                continue
            new_lines = []
            product = detail.product_id
            account_id = product.property_account_income_id.id \
                or product.categ_id.property_account_income_categ_id.id
            if detail.late_fee_amount:
                new_lines.append({
                    'name': 'Late Fee',
                    'account_id': account_id,
                    'price_unit': detail.late_fee_amount,
                    'quantity': 1.0,
                })
            if detail.waiver_amount:
                new_lines.append({
                    'name': 'Fee Exemption / Scholarship Waiver',
                    'account_id': account_id,
                    'price_unit': -detail.waiver_amount,
                    'quantity': 1.0,
                })
            if new_lines:
                detail.invoice_id.write({'invoice_line_ids': [(0, 0, line) for line in new_lines]})
                detail.invoice_id._compute_tax_totals()
        return res

    def action_view_fee_invoice(self):
        """OpenEduCat's own action_get_invoice() hardcodes the legacy 'tree'
        view type in its views tuple, which Odoo 19 renamed to 'list' - it
        raises a client-side error there. This opens the same invoice with a
        plain, single-view action instead of going through that method.
        """
        self.ensure_one()
        if not self.invoice_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoice',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.invoice_id.id,
        }


class OpStudent(models.Model):
    _inherit = 'op.student'

    def action_view_fee_collection(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Fee Collection',
            'res_model': 'op.student.fees.details',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }
