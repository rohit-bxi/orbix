# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

import secrets

from odoo import fields, models


class RteLotteryWizard(models.TransientModel):
    _name = 'rte.lottery.wizard'
    _description = 'RTE Lottery Wizard'

    course_id = fields.Many2one(
        'op.course', string='Course', required=True,
        domain=[('rte_active', '=', True)])
    academic_year_id = fields.Many2one(
        'op.academic.year', string='Academic Year', required=True)
    random_seed = fields.Char(
        string='Random Seed', required=True, readonly=True,
        default=lambda self: secrets.token_hex(16),
        help='Generated fresh, server-side, each time this wizard opens - '
             'not editable. Letting an operator pick or retry the seed '
             'would let them influence who lands inside the cutoff before '
             'committing to a draw; the seed is still recorded on the '
             'batch afterwards for audit/reproducibility.')

    def action_create_and_run(self):
        self.ensure_one()
        batch = self.env['rte.lottery.batch'].create({
            'course_id': self.course_id.id,
            'academic_year_id': self.academic_year_id.id,
            'random_seed': self.random_seed,
        })
        batch.action_mark_ready()
        batch.run_lottery()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lottery Batch',
            'res_model': 'rte.lottery.batch',
            'view_mode': 'form',
            'res_id': batch.id,
            'target': 'current',
        }
