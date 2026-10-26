# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL


class BxiPaymentOrder(models.Model):
    """One Razorpay checkout attempt. `purpose` says what a verified payment
    pays for: a fee line here (reconciled through bxi_fee_management's
    existing bxi.fee.payment.wizard), or anything another module adds to
    the selection (e.g. bxi_api_support's canteen wallet top-ups) together
    with a matching `_reconcile_<purpose>` method. This model never touches
    accounting directly, it only decides *when* to trigger that flow and
    with which reference.
    """
    _name = 'bxi.payment.order'
    _description = 'Orbix Online Payment Order'
    _order = 'create_date desc'

    purpose = fields.Selection([('fee', 'Fee Payment')], required=True, default='fee', readonly=True)
    fees_detail_id = fields.Many2one('op.student.fees.details', string='Fee Line', index=True)
    student_id = fields.Many2one('op.student', string='Student', index=True, readonly=True)
    currency_id = fields.Many2one(
        'res.currency', required=True, readonly=True, default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary(required=True)
    user_id = fields.Many2one('res.users', string='Initiated By', required=True)

    razorpay_order_id = fields.Char(readonly=True, copy=False)
    razorpay_payment_id = fields.Char(readonly=True, copy=False)
    razorpay_signature = fields.Char(readonly=True, copy=False)

    status = fields.Selection([
        ('created', 'Created'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
    ], default='created', required=True, readonly=True, copy=False)

    @api.model
    def _create_for_fee_line(self, fees_detail, amount, user):
        if amount <= 0:
            raise UserError(_('Enter a payment amount greater than zero.'))
        if amount > fees_detail.amount_pending + 0.01:
            raise UserError(_('Payment amount cannot exceed the pending amount of %s.') % fees_detail.amount_pending)
        return self._create_with_gateway({
            'purpose': 'fee',
            'fees_detail_id': fees_detail.id,
            'student_id': fees_detail.student_id.id,
            'currency_id': (fees_detail.currency_id or self.env.company.currency_id).id,
            'amount': amount,
            'user_id': user.id,
        })

    @api.model
    def _create_with_gateway(self, vals):
        """Create the order and its Razorpay counterpart. Returns the order,
        or None when Razorpay refused/was unreachable (the order is kept as
        'failed' for the audit trail)."""
        order = self.sudo().create(vals)
        rp_order = self.env['bxi.razorpay.client'].sudo().create_order(
            amount=order.amount, currency=order.currency_id.name or 'INR', receipt=f'orbix-{order.id}')
        if not rp_order:
            order.status = 'failed'
            return None
        order.razorpay_order_id = rp_order['id']
        return order

    def _default_journal(self):
        journal_id = self.env['ir.config_parameter'].sudo().get_param('bxi_online_fee_payment.default_journal_id')
        return self.env['account.journal'].sudo().browse(int(journal_id)) if journal_id else self.env['account.journal']

    def _reconcile_payment(self):
        """Book the verified payment for whatever `purpose` it was for,
        then mark the order paid."""
        self.ensure_one()
        getattr(self, '_reconcile_%s' % self.purpose)()
        self.status = 'paid'

    def _reconcile_fee(self):
        """Runs bxi.fee.payment.wizard as if a staff member had recorded
        this payment manually - same accounting path, same guarantees
        (invoice auto-created/posted if needed, partial-payment rules
        enforced), just triggered by a verified Razorpay signature instead
        of a form submit.
        """
        journal = self._default_journal()
        if not journal:
            raise UserError(_('No default online-payment journal is configured (Settings > Orbix Payments).'))

        wizard = self.env['bxi.fee.payment.wizard'].sudo().create({
            'fees_detail_id': self.fees_detail_id.id,
            'amount': self.amount,
            'payment_mode': 'online',
            'payment_date': fields.Date.context_today(self),
            'journal_id': journal.id,
            'reference': self.razorpay_payment_id,
            'memo': f'Razorpay payment {self.razorpay_payment_id} (order {self.razorpay_order_id})',
        })
        wizard.action_confirm()

    def _lock_and_check_paid(self):
        """Row-lock this order and re-read its status, so the app's /verify
        call and Razorpay's webhook arriving at the same moment can't both
        reconcile (and double-book) the same payment. True if already paid.
        """
        self.env.execute_query(SQL('SELECT id FROM bxi_payment_order WHERE id = %s FOR UPDATE', self.id))
        self.invalidate_recordset(['status'])
        return self.status == 'paid'

    def _mark_paid_from_client(self, razorpay_payment_id, razorpay_signature):
        """Called from the app-facing /verify endpoint. Returns True/False;
        never raises for a bad signature, only for genuine reconciliation
        errors (e.g. amount now exceeds pending because of a race), so the
        caller can tell "signature was wrong" apart from "something broke".
        """
        self.ensure_one()
        if self._lock_and_check_paid():
            return True
        client = self.env['bxi.razorpay.client'].sudo()
        if not client.verify_payment_signature(self.razorpay_order_id, razorpay_payment_id, razorpay_signature):
            self.status = 'failed'
            return False
        self.write({'razorpay_payment_id': razorpay_payment_id, 'razorpay_signature': razorpay_signature})
        self._reconcile_payment()
        return True

    def _mark_paid_from_webhook(self, razorpay_payment_id):
        """Called from the public /webhook endpoint, after the caller has
        already verified the webhook signature against the raw body -
        there is no per-order signature to check here, Razorpay's webhook
        signature already authenticates the whole payload.
        """
        self.ensure_one()
        if self._lock_and_check_paid():
            return True
        self.write({'razorpay_payment_id': razorpay_payment_id})
        self._reconcile_payment()
        return True
