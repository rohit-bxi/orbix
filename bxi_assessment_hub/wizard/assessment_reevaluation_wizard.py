# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import _, api, fields, models


class BxiAssessmentReevaluationWizard(models.TransientModel):
    _name = 'bxi.assessment.reevaluation.wizard'
    _description = 'Re-evaluate Submission'

    submission_id = fields.Many2one('bxi.assessment.submission', string='Submission', required=True)
    original_score = fields.Float(related='submission_id.total_score', readonly=True)
    max_score = fields.Float(related='submission_id.max_score', readonly=True)
    marks_adjustment = fields.Float(
        string='Marks Adjustment', default=0.0,
        help='Added on top of the current score. Use a negative number to deduct marks.')
    estimated_new_score = fields.Float(compute='_compute_estimated_new_score', string='Estimated New Score')
    reason = fields.Text(string='Re-evaluation Reason', required=True)

    @api.depends('original_score', 'marks_adjustment', 'max_score')
    def _compute_estimated_new_score(self):
        for wizard in self:
            score = wizard.original_score + wizard.marks_adjustment
            if wizard.max_score:
                score = min(score, wizard.max_score)
            wizard.estimated_new_score = max(0.0, score)

    def action_confirm(self):
        self.ensure_one()
        submission = self.submission_id
        old_score = submission.total_score
        submission.manual_adjustment += self.marks_adjustment
        submission.status = 'reviewed'
        submission.reevaluation_reason = self.reason
        submission.message_post(body=_(
            'Re-evaluated: %(old).1f -> %(new).1f. Reason: %(reason)s'
        ) % {'old': old_score, 'new': submission.total_score, 'reason': self.reason})
        return {'type': 'ir.actions.act_window_close'}
