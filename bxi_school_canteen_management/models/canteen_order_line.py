from odoo import fields, models, api


class CanteenOrderLine(models.Model):
    _name = 'bxi.canteen.order.line'
    _description = 'Canteen Order Line'

    order_id = fields.Many2one('bxi.canteen.order', required=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', required=True,
        domain=[('is_canteen_item', '=', True), ('available_today', '=', True)])
    quantity = fields.Float(default=1.0, required=True)
    price_unit = fields.Monetary()
    price_subtotal = fields.Monetary(compute='_compute_price_subtotal', store=True)
    currency_id = fields.Many2one(related='order_id.currency_id')

    @api.depends('quantity', 'price_unit')
    def _compute_price_subtotal(self):
        for line in self:
            line.price_subtotal = line.quantity * line.price_unit

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.price_unit = self.product_id.list_price
