# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BxiAssessmentSubmission(models.Model):
    _name = 'bxi.assessment.submission'
    _description = 'Assessment Submission'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    session_id = fields.Many2one('bxi.assessment.session', string='Session', required=True, ondelete='cascade')
    exam_id = fields.Many2one(related='session_id.exam_id', string='Exam', store=True, readonly=True)
    student_id = fields.Many2one('op.student', string='Student', required=True, tracking=True)
    submitted_at = fields.Datetime(string='Submitted At', readonly=True, copy=False)
    status = fields.Selection([
        ('not_submitted', 'Not Submitted'),
        ('submitted', 'Pending Review'),
        ('auto_graded', 'Auto Graded'),
        ('reviewed', 'Reviewed'),
    ], default='not_submitted', required=True, tracking=True)
    grading_strictness = fields.Selection([
        ('lenient', 'Lenient'),
        ('medium', 'Medium - Balanced Approach'),
        ('strict', 'Strict'),
    ], default='medium', required=True)
    answer_ids = fields.One2many('bxi.assessment.submission.answer', 'submission_id', string='Answers')
    max_score = fields.Float(related='exam_id.total_marks', string='Max Score', readonly=True)
    computed_score = fields.Float(compute='_compute_computed_score', store=True, string='Computed Score')
    manual_adjustment = fields.Float(default=0.0, copy=False)
    total_score = fields.Float(compute='_compute_total_score', store=True, string='Score')
    reevaluation_reason = fields.Text(copy=False)

    @api.depends('answer_ids.awarded_marks')
    def _compute_computed_score(self):
        for submission in self:
            submission.computed_score = sum(submission.answer_ids.mapped('awarded_marks'))

    @api.depends('computed_score', 'manual_adjustment', 'max_score')
    def _compute_total_score(self):
        for submission in self:
            score = submission.computed_score + submission.manual_adjustment
            if submission.max_score:
                score = min(score, submission.max_score)
            submission.total_score = max(0.0, score)

    def action_mark_submitted(self):
        for submission in self:
            unanswered = submission.answer_ids.filtered(
                lambda a: not a.student_answer_text and not a.selected_option_id)
            if unanswered:
                raise UserError(_(
                    'Every question needs an answer before this submission can be marked submitted.'))
            submission.write({'status': 'submitted', 'submitted_at': fields.Datetime.now()})

    def action_auto_grade(self):
        for submission in self:
            if submission.status not in ('submitted', 'auto_graded'):
                raise UserError(_('Only submitted submissions can be auto-graded.'))
            errors = []
            for answer in submission.answer_ids:
                try:
                    answer._grade(submission.grading_strictness)
                except UserError as exc:
                    errors.append(str(exc))
            submission.status = 'auto_graded'
            if errors:
                submission.message_post(
                    body=_('Auto-grading completed with issues:<br/>%s') % '<br/>'.join(errors))
