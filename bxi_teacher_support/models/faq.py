# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, models


class BxiFaq(models.Model):
    _name = 'bxi.faq'
    _description = 'Frequently Asked Question'
    _order = 'sequence, id'

    question = fields.Char(required=True)
    answer = fields.Html(required=True)
    category = fields.Char()
    audience = fields.Selection([
        ('all', 'All'),
        ('student', 'Student'),
        ('parent', 'Parent'),
        ('teacher', 'Teacher'),
    ], default='all', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
