from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class UniformStock(models.Model):
    _name = 'bxi.uniform.stock'
    _description = 'Uniform Item Stock'
    _rec_name = 'product_id'

    product_id = fields.Many2one('product.product', required=True, ondelete='cascade')
    product_tmpl_id = fields.Many2one(related='product_id.product_tmpl_id', store=True)
    quantity_on_hand = fields.Float(compute='_compute_quantity_on_hand', store=True)
    reorder_level = fields.Float(default=0.0)
    is_low_stock = fields.Boolean(compute='_compute_quantity_on_hand', store=True)
    move_ids = fields.One2many('bxi.uniform.stock.move', 'stock_id', string='Stock Moves')
    move_count = fields.Integer(compute='_compute_move_count')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    _unique_product = models.Constraint(
        'unique(product_id)',
        'A stock record already exists for this item.',
    )

    @api.depends('move_ids.quantity', 'move_ids.state', 'reorder_level')
    def _compute_quantity_on_hand(self):
        for stock in self:
            posted = stock.move_ids.filtered(lambda m: m.state == 'posted')
            stock.quantity_on_hand = sum(posted.mapped('quantity'))
            stock.is_low_stock = stock.quantity_on_hand <= stock.reorder_level

    def _compute_move_count(self):
        for stock in self:
            stock.move_count = len(stock.move_ids)

    @api.model
    def _get_or_create(self, product_id):
        stock = self.search([('product_id', '=', product_id)], limit=1)
        if not stock:
            stock = self.create({'product_id': product_id})
        return stock

    def action_view_moves(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Stock Moves',
            'res_model': 'bxi.uniform.stock.move',
            'view_mode': 'list,form',
            'domain': [('stock_id', '=', self.id)],
            'context': {'default_stock_id': self.id},
        }

    def action_receive_stock(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Receive Stock',
            'res_model': 'bxi.uniform.stock.move',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_stock_id': self.id, 'default_move_type': 'receipt'},
        }
