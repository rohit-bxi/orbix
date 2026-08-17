from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class CanteenWalletTransaction(models.Model):
    _name = 'bxi.canteen.wallet.transaction'
    _description = 'Canteen Wallet Transaction'
    _order = 'date desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default=lambda self: _('New'))
    wallet_id = fields.Many2one('bxi.canteen.wallet', required=True, ondelete='restrict')
    transaction_type = fields.Selection([
        ('topup', 'Top-up'),
        ('order_payment', 'Order Payment'),
        ('refund', 'Refund'),
        ('adjustment', 'Adjustment'),
    ], required=True)
    amount = fields.Monetary(required=True, help='Signed: positive for credit, negative for debit.')
    currency_id = fields.Many2one(related='wallet_id.currency_id', store=True)
    date = fields.Datetime(default=fields.Datetime.now, required=True)
    order_id = fields.Many2one('bxi.canteen.order', ondelete='set null')
    payment_method = fields.Selection([
        ('cash', 'Cash'),
        ('card', 'Card'),
        ('online', 'Online'),
    ])
    account_payment_id = fields.Many2one('account.payment', readonly=True)
    processed_by = fields.Many2one('res.users', default=lambda self: self.env.user)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ], default='posted', required=True)
    note = fields.Char()
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.canteen.wallet.transaction') or _('New')
        return super().create(vals_list)

    @api.constrains('amount', 'transaction_type')
    def _check_amount_sign(self):
        for record in self:
            if record.transaction_type in ('topup', 'refund') and record.amount <= 0:
                raise ValidationError(_('%s amount must be positive.') % dict(self._fields['transaction_type'].selection).get(record.transaction_type))
            if record.transaction_type == 'order_payment' and record.amount >= 0:
                raise ValidationError(_('Order payment amount must be negative.'))
            if record.transaction_type == 'adjustment' and record.amount == 0:
                raise ValidationError(_('Adjustment amount cannot be zero.'))
