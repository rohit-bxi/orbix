from odoo import fields, models, api, _
from odoo.exceptions import ValidationError, UserError


class UniformExchangeWizard(models.TransientModel):
    _name = 'bxi.uniform.exchange.wizard'
    _description = 'Uniform Size Exchange'

    order_line_id = fields.Many2one(
        'bxi.uniform.order.line', required=True,
        domain="[('order_id.state', '=', 'issued')]")
    order_id = fields.Many2one(related='order_line_id.order_id', readonly=True)
    old_product_id = fields.Many2one(related='order_line_id.product_id', readonly=True)
    quantity = fields.Float(related='order_line_id.quantity', readonly=True)
    new_product_id = fields.Many2one(
        'product.product', required=True, string='New Size/Item',
        domain=[('is_uniform_item', '=', True)])
    note = fields.Char()

    def action_exchange(self):
        self.ensure_one()
        line = self.order_line_id
        if self.new_product_id == line.product_id:
            raise ValidationError(_('The new item must be different from the current one.'))
        new_stock = self.env['bxi.uniform.stock']._get_or_create(self.new_product_id.id)
        if new_stock.quantity_on_hand < line.quantity:
            raise UserError(_('Insufficient stock for %s (available %s, needed %s).') % (
                self.new_product_id.display_name, new_stock.quantity_on_hand, line.quantity))

        old_stock = self.env['bxi.uniform.stock']._get_or_create(line.product_id.id)
        self.env['bxi.uniform.stock.move'].create({
            'stock_id': old_stock.id,
            'move_type': 'return',
            'quantity': line.quantity,
            'order_id': line.order_id.id,
            'note': self.note or _('Size exchange'),
        })
        self.env['bxi.uniform.stock.move'].create({
            'stock_id': new_stock.id,
            'move_type': 'issue',
            'quantity': -line.quantity,
            'order_id': line.order_id.id,
            'note': self.note or _('Size exchange'),
        })
        line.write({
            'product_id': self.new_product_id.id,
            'price_unit': self.new_product_id.list_price,
        })
        return {'type': 'ir.actions.act_window_close'}
