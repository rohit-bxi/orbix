from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_uniform_item = fields.Boolean(string='Uniform Item')
    uniform_gender = fields.Selection([
        ('boy', 'Boy'),
        ('girl', 'Girl'),
        ('unisex', 'Unisex'),
    ], string='Gender', default='unisex')
    uniform_season = fields.Selection([
        ('summer', 'Summer'),
        ('winter', 'Winter'),
        ('all_season', 'All Season'),
        ('sports', 'Sports / PE'),
    ], string='Season', default='all_season')
