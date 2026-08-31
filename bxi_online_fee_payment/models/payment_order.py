# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BxiPaymentOrder(models.Model):
    """One Razorpay checkout attempt against one fee line. Reconciliation
    on success goes through bxi_fee_management's existing
    bxi.fee.payment.wizard (account.payment.register underneath) - this
    model never touches accounting directly, it only decides *when* to
    trigger that flow and with which reference.
    """
    _name = 'bxi.payment.order'
    _description = 'Orbix Online Payment Order'
    _order = 'create_date desc'

    fees_detail_id = fields.Many2one('op.student.fees.details', string='Fee Line', required=True, index=True)
    student_id = fields.Many2one(related='fees_detail_id.student_id', store=True, readonly=True)
    currency_id = fields.Many2one(related='fees_detail_id.currency_id', readonly=True)
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

        order = self.sudo().create({
            'fees_detail_id': fees_detail.id,
            'amount': amount,
            'user_id': user.id,
        })
        receipt = f'orbix-{order.id}'
        rp_order = self.env['bxi.razorpay.client'].sudo().create_order(
            amount=amount, currency=fees_detail.currency_id.name or 'INR', receipt=receipt)
        if not rp_order:
            order.status = 'failed'
            return None
        order.razorpay_order_id = rp_order['id']
        return order

    def _default_journal(self):
        journal_id = self.env['ir.config_parameter'].sudo().get_param('bxi_online_fee_payment.default_journal_id')
        return self.env['account.journal'].sudo().browse(int(journal_id)) if journal_id else self.env['account.journal']

    def _reconcile_payment(self):
        """Runs bxi.fee.payment.wizard as if a staff member had recorded
        this payment manually - same accounting path, same guarantees
        (invoice auto-created/posted if needed, partial-payment rules
        enforced), just triggered by a verified Razorpay signature instead
        of a form submit.
        """
        self.ensure_one()
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
        self.status = 'paid'

    def _mark_paid_from_client(self, razorpay_payment_id, razorpay_signature):
        """Called from the app-facing /verify endpoint. Returns True/False;
        never raises for a bad signature, only for genuine reconciliation
        errors (e.g. amount now exceeds pending because of a race), so the
        caller can tell "signature was wrong" apart from "something broke".
        """
        self.ensure_one()
        if self.status == 'paid':
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
        if self.status == 'paid':
            return True
        self.write({'razorpay_payment_id': razorpay_payment_id})
        self._reconcile_payment()
        return True
