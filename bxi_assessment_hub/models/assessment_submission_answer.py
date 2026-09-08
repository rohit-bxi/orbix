# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import _, fields, models


class BxiAssessmentSubmissionAnswer(models.Model):
    _name = 'bxi.assessment.submission.answer'
    _description = 'Assessment Submission Answer'
    _order = 'submission_id, question_id'

    submission_id = fields.Many2one(
        'bxi.assessment.submission', string='Submission', required=True, ondelete='cascade', index=True)
    question_id = fields.Many2one('bxi.exam.question', string='Question', required=True, ondelete='restrict')
    question_type = fields.Selection(related='question_id.question_type', store=True)
    marks = fields.Float(related='question_id.marks', string='Max Marks')
    student_answer_text = fields.Text(string='Student Answer')
    selected_option_id = fields.Many2one('bxi.exam.question.option', string='Selected Option')
    awarded_marks = fields.Float(string='Awarded Marks', default=0.0)
    ai_rationale = fields.Text(string='AI Rationale', readonly=True)
    is_ai_graded = fields.Boolean(string='AI Graded', readonly=True)

    def _grade(self, strictness):
        self.ensure_one()
        if self.question_type == 'mcq':
            self.write({
                'awarded_marks': self.marks if (
                    self.selected_option_id and self.selected_option_id.is_correct) else 0.0,
                'is_ai_graded': False,
                'ai_rationale': False,
            })
            return
        if not self.student_answer_text:
            self.write({'awarded_marks': 0.0, 'ai_rationale': _('No answer submitted.'), 'is_ai_graded': False})
            return
        result = self.env['bxi.ai.client'].grade_answer(
            question_text=self.question_id.question_text,
            sample_answer_keywords=self.question_id.sample_answer_keywords or '',
            student_answer=self.student_answer_text,
            max_marks=self.marks,
            strictness=strictness,
        )
        self.write({
            'awarded_marks': result['awarded_marks'],
            'ai_rationale': result.get('rationale'),
            'is_ai_graded': True,
        })
