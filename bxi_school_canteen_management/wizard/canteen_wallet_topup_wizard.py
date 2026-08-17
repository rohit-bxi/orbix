from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class CanteenWalletTopupWizard(models.TransientModel):
    _name = 'bxi.canteen.wallet.topup.wizard'
    _description = 'Top Up Canteen Wallet'

    patron_type = fields.Selection([
        ('student', 'Student'),
        ('faculty', 'Teacher'),
    ], required=True, default='student')
    student_id = fields.Many2one('op.student')
    faculty_id = fields.Many2one('op.faculty')
    amount = fields.Monetary(required=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    payment_method = fields.Selection([
        ('cash', 'Cash'),
        ('card', 'Card'),
        ('online', 'Online'),
    ], required=True, default='cash')
    post_to_accounting = fields.Boolean(default=True)
    journal_id = fields.Many2one(
        'account.journal', domain=[('type', 'in', ('bank', 'cash'))])

    @api.constrains('amount')
    def _check_amount(self):
        for record in self:
            if record.amount <= 0:
                raise ValidationError(_('Top-up amount must be greater than zero.'))

    def action_topup(self):
        self.ensure_one()
        patron = self.student_id if self.patron_type == 'student' else self.faculty_id
        if not patron:
            raise ValidationError(_('Please select a patron.'))

        wallet = patron.wallet_ids[:1]
        if not wallet:
            wallet_vals = {'student_id': patron.id} if self.patron_type == 'student' else {'faculty_id': patron.id}
            wallet = self.env['bxi.canteen.wallet'].create(wallet_vals)

        payment = False
        if self.post_to_accounting:
            if not self.journal_id:
                raise ValidationError(_('Please select a payment journal to post this top-up to accounting.'))
            payment = self.env['account.payment'].create({
                'payment_type': 'inbound',
                'partner_id': patron.partner_id.id,
                'amount': self.amount,
                'journal_id': self.journal_id.id,
                'memo': _('Canteen Wallet Top-up - %s') % patron.name,
            })
            payment.action_post()

        self.env['bxi.canteen.wallet.transaction'].create({
            'wallet_id': wallet.id,
            'transaction_type': 'topup',
            'amount': self.amount,
            'state': 'posted',
            'payment_method': self.payment_method,
            'account_payment_id': payment.id if payment else False,
        })
        return {'type': 'ir.actions.act_window_close'}
