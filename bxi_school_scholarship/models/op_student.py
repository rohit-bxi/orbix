# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import api, fields, models


class OpStudent(models.Model):
    _inherit = 'op.student'

    scholarship_ids = fields.One2many('bxi.student.scholarship', 'student_id', string='Scholarships')
    scholarship_count = fields.Integer(compute='_compute_scholarship_count')

    @api.depends('scholarship_ids')
    def _compute_scholarship_count(self):
        for student in self:
            student.scholarship_count = len(student.scholarship_ids)

    def action_view_scholarships(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Scholarships',
            'res_model': 'bxi.student.scholarship',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }
