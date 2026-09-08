# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BxiAssessmentAutogradeWizard(models.TransientModel):
    _name = 'bxi.assessment.autograde.wizard'
    _description = 'Auto-Grade Pending Submissions'

    submission_ids = fields.Many2many(
        'bxi.assessment.submission', string='Pending Submissions',
        default=lambda self: self.env['bxi.assessment.submission'].search([('status', '=', 'submitted')]))
    submission_count = fields.Integer(compute='_compute_submission_count')
    state = fields.Selection([('confirm', 'Confirm'), ('done', 'Done')], default='confirm', required=True)
    graded_count = fields.Integer(readonly=True)
    failed_count = fields.Integer(readonly=True)

    @api.depends('submission_ids')
    def _compute_submission_count(self):
        for wizard in self:
            wizard.submission_count = len(wizard.submission_ids)

    def action_start_grading(self):
        self.ensure_one()
        if not self.submission_ids:
            raise UserError(_('There are no pending submissions to grade.'))
        config = self.env['bxi.ai.client']._get_config()
        if not config.get('api_key'):
            raise UserError(_(
                'AI grading is not configured. Add an API key under Settings > Assessments & Exams.'))

        graded = 0
        failed = 0
        for submission in self.submission_ids:
            try:
                submission.action_auto_grade()
                graded += 1
            except Exception:
                failed += 1
                _logger.exception('Auto-grading failed for submission %s.', submission.id)

        self.write({'state': 'done', 'graded_count': graded, 'failed_count': failed})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
