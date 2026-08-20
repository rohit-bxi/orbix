from odoo import fields, models, api, _


class UniformOrderLine(models.Model):
    _name = 'bxi.uniform.order.line'
    _description = 'Uniform Order Line'

    order_id = fields.Many2one('bxi.uniform.order', required=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', required=True,
        domain=[('is_uniform_item', '=', True)])
    quantity = fields.Float(default=1.0, required=True)
    price_unit = fields.Monetary()
    price_subtotal = fields.Monetary(compute='_compute_price_subtotal', store=True)
    currency_id = fields.Many2one(related='order_id.currency_id')

    def _compute_display_name(self):
        for line in self:
            line.display_name = _('%(order)s - %(product)s (Qty: %(qty)s)') % {
                'order': line.order_id.name or _('New'),
                'product': line.product_id.display_name or _('Unset Item'),
                'qty': line.quantity,
            }

    @api.depends('quantity', 'price_unit')
    def _compute_price_subtotal(self):
        for line in self:
            line.price_subtotal = line.quantity * line.price_unit

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.price_unit = self.product_id.list_price
