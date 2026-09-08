# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import api, fields, models


class OpStudent(models.Model):
    _inherit = 'op.student'

    exemption_request_ids = fields.One2many(
        'bxi.fee.exemption.request', 'student_id', string='Fee Exemption Requests')
    exemption_request_count = fields.Integer(compute='_compute_exemption_request_count')

    exemption_ids = fields.One2many('bxi.fee.exemption', 'student_id', string='Fee Exemptions')
    exemption_count = fields.Integer(compute='_compute_exemption_count')

    @api.depends('exemption_request_ids')
    def _compute_exemption_request_count(self):
        for student in self:
            student.exemption_request_count = len(student.exemption_request_ids)

    @api.depends('exemption_ids')
    def _compute_exemption_count(self):
        for student in self:
            student.exemption_count = len(student.exemption_ids)

    def action_view_exemption_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Fee Exemption Requests',
            'res_model': 'bxi.fee.exemption.request',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }

    def action_view_exemptions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Fee Exemptions',
            'res_model': 'bxi.fee.exemption',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }
