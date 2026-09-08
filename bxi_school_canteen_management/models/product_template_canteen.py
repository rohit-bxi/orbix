# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
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
