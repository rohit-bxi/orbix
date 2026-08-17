from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class CanteenWallet(models.Model):
    _name = 'bxi.canteen.wallet'
    _description = 'Canteen Wallet'
    _inherit = ['mail.thread', 'bxi.canteen.patron.mixin']
    _rec_name = 'patron_name'

    balance = fields.Monetary(compute='_compute_balance', store=True)
    transaction_ids = fields.One2many('bxi.canteen.wallet.transaction', 'wallet_id', string='Transactions')
    transaction_count = fields.Integer(compute='_compute_transaction_count')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    low_balance_threshold = fields.Monetary(default=0.0)
    is_low_balance = fields.Boolean(compute='_compute_balance', store=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('transaction_ids.amount', 'transaction_ids.state', 'low_balance_threshold')
    def _compute_balance(self):
        for wallet in self:
            posted = wallet.transaction_ids.filtered(lambda t: t.state == 'posted')
            wallet.balance = sum(posted.mapped('amount'))
            wallet.is_low_balance = wallet.balance <= wallet.low_balance_threshold

    def _compute_transaction_count(self):
        for wallet in self:
            wallet.transaction_count = len(wallet.transaction_ids)

    @api.constrains('student_id', 'faculty_id')
    def _check_single_wallet(self):
        for wallet in self:
            domain = [('id', '!=', wallet.id)]
            if wallet.student_id:
                domain.append(('student_id', '=', wallet.student_id.id))
            else:
                domain.append(('faculty_id', '=', wallet.faculty_id.id))
            if self.search_count(domain):
                raise ValidationError(_('This patron already has a wallet.'))

    def action_view_transactions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Transactions',
            'res_model': 'bxi.canteen.wallet.transaction',
            'view_mode': 'list,form',
            'domain': [('wallet_id', '=', self.id)],
            'context': {'default_wallet_id': self.id},
        }

    def action_open_topup_wizard(self):
        self.ensure_one()
        context = {'default_patron_type': self.patron_type}
        if self.patron_type == 'student':
            context['default_student_id'] = self.student_id.id
        else:
            context['default_faculty_id'] = self.faculty_id.id
        return {
            'type': 'ir.actions.act_window',
            'name': 'Top Up Wallet',
            'res_model': 'bxi.canteen.wallet.topup.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': context,
        }
