# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import _, fields, models


class BxiExamQuestion(models.Model):
    _name = 'bxi.exam.question'
    _description = 'Exam Question'
    _order = 'exam_id, sequence, id'
    _rec_name = 'question_text'

    exam_id = fields.Many2one('bxi.exam', string='Exam', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    question_type = fields.Selection([
        ('mcq', 'Multiple Choice'),
        ('short_answer', 'Short Answer'),
        ('long_answer', 'Long Answer'),
    ], string='Question Type', required=True, default='short_answer')
    question_text = fields.Text(string='Question', required=True)
    marks = fields.Float(string='Marks', required=True, default=1)
    sample_answer_keywords = fields.Text(
        string='Sample Answer / Keywords',
        help='Reference answer or key concepts used to auto-grade short/long answer responses.')
    option_ids = fields.One2many('bxi.exam.question.option', 'question_id', string='Answer Options', copy=True)

    def _mcq_publish_error(self):
        """Return an error message if this question isn't a well-formed MCQ
        yet, or False if it's fine (or not an MCQ). Not enforced as an
        @api.constrains: a question is commonly built up incrementally -
        created first, then its option lines created one at a time (as the
        AI assignment generator will do) - so validating on every write
        would reject perfectly normal in-progress states. Checked instead
        at exam-publish time, when the question is expected to be complete.
        """
        self.ensure_one()
        if self.question_type != 'mcq':
            return False
        label = self.question_text or _('Untitled question')
        if len(self.option_ids) < 2:
            return _('"%s" needs at least two answer options.') % label
        if len(self.option_ids.filtered('is_correct')) != 1:
            return _('"%s" must have exactly one correct answer option.') % label
        return False
