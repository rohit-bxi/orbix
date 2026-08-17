from odoo import fields, models, api, _
from odoo.exceptions import ValidationError, AccessError


class CanteenOrder(models.Model):
    _name = 'bxi.canteen.order'
    _description = 'Canteen Order'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'bxi.canteen.patron.mixin']
    _order = 'order_datetime desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default=lambda self: _('New'))
    order_datetime = fields.Datetime(required=True, default=fields.Datetime.now, tracking=True)
    order_line_ids = fields.One2many('bxi.canteen.order.line', 'order_id', string='Order Lines')
    total_amount = fields.Monetary(compute='_compute_total_amount', store=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    wallet_id = fields.Many2one('bxi.canteen.wallet', compute='_compute_wallet_id', store=True)
    wallet_balance = fields.Monetary(related='wallet_id.balance', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('preparing', 'Preparing'),
        ('ready', 'Ready'),
        ('served', 'Served'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True)
    served_by = fields.Many2one('hr.employee')
    cancel_reason = fields.Char()
    debit_transaction_id = fields.Many2one('bxi.canteen.wallet.transaction', readonly=True, copy=False)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('order_line_ids.price_subtotal')
    def _compute_total_amount(self):
        for order in self:
            order.total_amount = sum(order.order_line_ids.mapped('price_subtotal'))

    @api.depends('student_id.wallet_ids', 'faculty_id.wallet_ids')
    def _compute_wallet_id(self):
        for order in self:
            wallets = order.student_id.wallet_ids or order.faculty_id.wallet_ids
            order.wallet_id = wallets[:1]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.canteen.order') or _('New')
        return super().create(vals_list)

    def _debit_wallet(self):
        self.ensure_one()
        txn = self.env['bxi.canteen.wallet.transaction'].create({
            'wallet_id': self.wallet_id.id,
            'transaction_type': 'order_payment',
            'amount': -self.total_amount,
            'state': 'posted',
            'order_id': self.id,
        })
        self.debit_transaction_id = txn.id

    def action_confirm(self):
        for order in self:
            if not order.wallet_id:
                raise ValidationError(_('No wallet found for this patron.'))
            if order.wallet_id.balance < order.total_amount:
                raise ValidationError(_('Insufficient wallet balance. Available: %(balance)s, Required: %(total)s') % {
                    'balance': order.wallet_id.balance, 'total': order.total_amount,
                })
            order._debit_wallet()
            order.write({'state': 'confirmed'})

    def action_force_confirm(self):
        if not self.env.user.has_group('bxi_school_canteen_management.group_canteen_manager'):
            raise AccessError(_('Only a Canteen Manager can force-confirm an order over wallet balance.'))
        for order in self:
            if not order.wallet_id:
                raise ValidationError(_('No wallet found for this patron.'))
            order._debit_wallet()
            order.write({'state': 'confirmed'})

    def action_preparing(self):
        self.write({'state': 'preparing'})

    def action_ready(self):
        self.write({'state': 'ready'})

    def action_served(self):
        self.write({'state': 'served'})

    def action_cancel(self):
        for order in self:
            if order.debit_transaction_id and order.state not in ('draft', 'cancelled'):
                self.env['bxi.canteen.wallet.transaction'].create({
                    'wallet_id': order.wallet_id.id,
                    'transaction_type': 'refund',
                    'amount': order.total_amount,
                    'state': 'posted',
                    'order_id': order.id,
                    'note': order.cancel_reason,
                })
            order.write({'state': 'cancelled'})
