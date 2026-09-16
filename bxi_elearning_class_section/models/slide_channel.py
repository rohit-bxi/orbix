# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SlideChannel(models.Model):
    _inherit = 'slide.channel'

    class_id = fields.Many2one('elearning.class', string='Class', index=True, tracking=True)
    section_id = fields.Many2one(
        'elearning.section', string='Section', index=True, tracking=True,
        domain="[('class_id', '=', class_id)]")

    @api.onchange('class_id')
    def _onchange_class_id(self):
        if self.section_id.class_id != self.class_id:
            self.section_id = False
