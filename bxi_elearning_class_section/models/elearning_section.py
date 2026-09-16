# -*- coding: utf-8 -*-
from odoo import fields, models


class ElearningSection(models.Model):
    _name = 'elearning.section'
    _description = 'eLearning Section'
    _inherit = ['website.published.mixin']
    _order = 'sequence asc, name asc'

    name = fields.Char('Section', required=True, translate=True)
    sequence = fields.Integer('Sequence', default=10, index=True)
    active = fields.Boolean(default=True)
    class_id = fields.Many2one('elearning.class', string='Class', required=True, ondelete='cascade', index=True)
    channel_ids = fields.One2many('slide.channel', 'section_id', string='Courses')
    channel_count = fields.Integer('Course Count', compute='_compute_channel_count')

    def _compute_channel_count(self):
        for rec in self:
            rec.channel_count = len(rec.channel_ids)

    def _default_is_published(self):
        return True
