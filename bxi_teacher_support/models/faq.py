# -*- coding: utf-8 -*-

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
