# -*- coding: utf-8 -*-

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
        string='Random Seed', required=True,
        default=lambda self: fields.Datetime.now().strftime('%Y%m%d%H%M%S'))

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
