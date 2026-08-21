from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.student_fees_details import PAYMENT_MODES


class FeePaymentWizard(models.TransientModel):
    """Records a manual/offline/partial fee payment. Builds on Odoo's own
    account.payment.register wizard for the actual reconciliation instead of
    creating and reconciling account.payment records by hand.
    """
    _name = 'bxi.fee.payment.wizard'
    _description = 'Record Fee Payment'

    fees_detail_id = fields.Many2one('op.student.fees.details', string='Fee Line', required=True)
    student_id = fields.Many2one(related='fees_detail_id.student_id', readonly=True)
    structure_id = fields.Many2one(related='fees_detail_id.structure_id', readonly=True)
    currency_id = fields.Many2one(related='fees_detail_id.currency_id', readonly=True)
    total_payable = fields.Monetary(related='fees_detail_id.total_payable', readonly=True)
    amount_pending = fields.Monetary(related='fees_detail_id.amount_pending', readonly=True)

    amount = fields.Monetary(required=True)
    payment_mode = fields.Selection(PAYMENT_MODES, required=True, default='cash')
    payment_date = fields.Date(required=True, default=fields.Date.context_today)
    journal_id = fields.Many2one(
        'account.journal', required=True, domain=[('type', 'in', ('bank', 'cash'))])
    reference = fields.Char(string='Transaction Reference')
    memo = fields.Char()

    @api.onchange('fees_detail_id')
    def _onchange_fees_detail_id(self):
        if self.fees_detail_id:
            self.amount = self.fees_detail_id.amount_pending

    def action_confirm(self):
        self.ensure_one()
        detail = self.fees_detail_id
        pending_before_invoice = detail.amount_pending
        if self.amount <= 0:
            raise UserError(_('Enter a payment amount greater than zero.'))
        if self.amount > pending_before_invoice + 0.01:
            raise UserError(
                _('Payment amount cannot exceed the pending amount of %s.') % pending_before_invoice)
        is_full_payment = self.amount >= pending_before_invoice - 0.01
        if not is_full_payment and not detail.structure_id.allow_partial_payment:
            raise UserError(_('Partial payments are not allowed for this fee structure.'))

        if not detail.invoice_id or detail.invoice_id.state == 'cancel':
            detail.get_invoice()
        if detail.invoice_id.state == 'draft':
            detail.invoice_id.action_post()

        # A fee line's invoice doesn't exist until this point, so "pay in full"
        # was necessarily quoted before the invoice's per-line rounding was
        # known. Settle against the invoice's real residual in that case so a
        # full payment always closes the invoice, instead of a rounding cent
        # leaving it stuck as partially paid.
        pay_amount = detail.invoice_id.amount_residual if is_full_payment else self.amount

        register = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=detail.invoice_id.ids,
            dont_redirect_to_payments=True,
        ).create({
            'amount': pay_amount,
            'payment_date': self.payment_date,
            'journal_id': self.journal_id.id,
            'communication': self.memo or self.reference or detail.student_id.name,
        })
        register.action_create_payments()
        detail.payment_mode = self.payment_mode
        return {'type': 'ir.actions.act_window_close'}
