from odoo import fields, models


class OpMediaCurriculum(models.Model):
    _inherit = 'op.media'

    curriculum_id = fields.Many2one('bxi.curriculum', string='Curriculum')
