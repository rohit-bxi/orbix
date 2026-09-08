# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BxiAiAssignmentGenerateWizard(models.TransientModel):
    _name = 'bxi.ai.assignment.generate.wizard'
    _description = 'Generate AI Assignment'

    exam_id = fields.Many2one(
        'bxi.exam', string='Existing Exam',
        help='Set when regenerating questions for an existing AI-generated exam; '
             'left empty to create a new one.')
    class_id = fields.Many2one('op.course', string='Class', required=True)
    subject_id = fields.Many2one('op.subject', string='Subject', required=True)
    topic = fields.Char(string='Topic', required=True)
    difficulty = fields.Selection([
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard'),
    ], string='Difficulty', required=True, default='medium')
    question_count = fields.Integer(string='Number of Questions', required=True, default=5)

    @api.constrains('question_count')
    def _check_question_count(self):
        for wizard in self:
            if not (1 <= wizard.question_count <= 20):
                raise UserError(_('Generate between 1 and 20 questions at a time.'))

    def action_generate(self):
        self.ensure_one()
        rows = self.env['bxi.ai.client'].generate_questions(
            course_name=self.class_id.name, subject_name=self.subject_id.name,
            topic=self.topic, difficulty=self.difficulty, count=self.question_count,
        )

        if self.exam_id:
            exam = self.exam_id
            exam.question_ids.unlink()
        else:
            exam = self.env['bxi.exam'].create({
                'name': _('%(subject)s - %(topic)s (AI Assignment)') % {
                    'subject': self.subject_id.name, 'topic': self.topic},
                'class_id': self.class_id.id,
                'subject_id': self.subject_id.id,
                'source': 'ai',
            })

        Question = self.env['bxi.exam.question']
        Option = self.env['bxi.exam.question.option']
        for row in rows:
            question = Question.create({
                'exam_id': exam.id,
                'question_type': row['question_type'],
                'question_text': row['question_text'],
                'marks': row['marks'],
                'sample_answer_keywords': row.get('sample_answer_keywords') or False,
            })
            for option in row.get('options') or []:
                Option.create({
                    'question_id': question.id,
                    'option_text': option['option_text'],
                    'is_correct': option['is_correct'],
                })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'bxi.exam',
            'res_id': exam.id,
            'views': [[False, 'form']],
            'target': 'current',
        }
