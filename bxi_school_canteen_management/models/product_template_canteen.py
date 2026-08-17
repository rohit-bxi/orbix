from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_canteen_item = fields.Boolean(string='Canteen Item')
    available_today = fields.Boolean(string='Available Today', default=True)
    veg_type = fields.Selection([
        ('veg', 'Veg'),
        ('non_veg', 'Non-Veg'),
        ('egg', 'Contains Egg'),
    ], string='Veg/Non-Veg', default='veg')
