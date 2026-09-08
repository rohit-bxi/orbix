# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import api, fields, models


class OpFaculty(models.Model):
    _inherit = 'op.faculty'

    coordinated_event_ids = fields.Many2many(
        'event.event', 'event_event_coordinator_rel', 'faculty_id', 'event_id',
        string='Coordinated Events', readonly=True)
    coordinated_event_count = fields.Integer(compute='_compute_coordinated_event_count')

    @api.depends('coordinated_event_ids')
    def _compute_coordinated_event_count(self):
        for rec in self:
            rec.coordinated_event_count = len(rec.coordinated_event_ids)

    def action_view_coordinated_events(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Coordinated Events',
            'res_model': 'event.event',
            'view_mode': 'list,kanban,calendar,form',
            'domain': [('coordinator_ids', '=', self.id)],
        }
