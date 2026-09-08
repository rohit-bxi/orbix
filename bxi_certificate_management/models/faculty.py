# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import api, fields, models


class OpFaculty(models.Model):
    _inherit = 'op.faculty'

    issued_certificate_count = fields.Integer(compute='_compute_issued_certificate_count')

    @api.depends()
    def _compute_issued_certificate_count(self):
        for rec in self:
            rec.issued_certificate_count = self.env['op.certificate'].search_count(
                [('issued_by', '=', rec.user_id.id)]) if rec.user_id else 0

    def action_view_issued_certificates(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Certificates Issued',
            'res_model': 'op.certificate',
            'view_mode': 'list,form',
            'domain': [('issued_by', '=', self.user_id.id)],
        }
