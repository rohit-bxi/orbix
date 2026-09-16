# -*- coding: utf-8 -*-
from odoo import fields, models


class ElearningClass(models.Model):
    _name = 'elearning.class'
    _description = 'eLearning Class'
    _inherit = ['website.published.mixin']
    _order = 'sequence asc, name asc'

    name = fields.Char('Class', required=True, translate=True)
    sequence = fields.Integer('Sequence', default=10, index=True)
    active = fields.Boolean(default=True)
    section_ids = fields.One2many('elearning.section', 'class_id', string='Sections')
    section_count = fields.Integer('Section Count', compute='_compute_section_count')
    channel_ids = fields.One2many('slide.channel', 'class_id', string='Courses')
    channel_count = fields.Integer('Course Count', compute='_compute_channel_count')

    def _compute_section_count(self):
        for rec in self:
            rec.section_count = len(rec.section_ids)

    def _compute_channel_count(self):
        for rec in self:
            rec.channel_count = len(rec.channel_ids)

    def _default_is_published(self):
        return True
