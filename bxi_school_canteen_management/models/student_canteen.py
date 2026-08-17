from odoo import fields, models, api


class OpStudent(models.Model):
    _name = 'op.student'
    _inherit = ['op.student']

    wallet_ids = fields.One2many('bxi.canteen.wallet', 'student_id', string='Canteen Wallets')
    order_ids = fields.One2many('bxi.canteen.order', 'student_id', string='Canteen Orders')
    canteen_currency_id = fields.Many2one('res.currency', compute='_compute_canteen_wallet_info')
    canteen_balance = fields.Monetary(compute='_compute_canteen_wallet_info', currency_field='canteen_currency_id')
    canteen_is_low_balance = fields.Boolean(compute='_compute_canteen_wallet_info')
    order_count = fields.Integer(compute='_compute_canteen_counts')

    @api.depends('wallet_ids.balance', 'wallet_ids.is_low_balance', 'wallet_ids.currency_id')
    def _compute_canteen_wallet_info(self):
        for record in self:
            wallet = record.wallet_ids[:1]
            record.canteen_balance = wallet.balance if wallet else 0.0
            record.canteen_is_low_balance = wallet.is_low_balance if wallet else False
            record.canteen_currency_id = wallet.currency_id if wallet else record.env.company.currency_id

    @api.depends('order_ids')
    def _compute_canteen_counts(self):
        for record in self:
            record.order_count = len(record.order_ids)

    def action_view_canteen_wallet(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Canteen Wallet',
            'res_model': 'bxi.canteen.wallet',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }

    def action_view_canteen_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Canteen Orders',
            'res_model': 'bxi.canteen.order',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }
