# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

SAMPLE_ROWS = [
    {'question_type': 'short_answer', 'question_text': 'Define inertia', 'marks': 2,
     'sample_answer_keywords': 'resistance to change in motion'},
    {'question_type': 'mcq', 'question_text': 'Unit of force?', 'marks': 1, 'options': [
        {'option_text': 'Newton', 'is_correct': True},
        {'option_text': 'Joule', 'is_correct': False},
    ]},
]


@tagged('post_install', '-at_install')
class TestAiAssignmentGenerateWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({'name': 'Class 10', 'code': 'AIC10'})
        cls.subject = cls.env['op.subject'].create({'name': 'Physics', 'code': 'AIPHY'})

    def _make_wizard(self, **overrides):
        vals = {
            'class_id': self.course.id, 'subject_id': self.subject.id,
            'topic': 'Motion', 'difficulty': 'medium', 'question_count': 2,
        }
        vals.update(overrides)
        return self.env['bxi.ai.assignment.generate.wizard'].create(vals)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.BxiAiClient.generate_questions')
    def test_generate_creates_new_ai_exam(self, mock_generate):
        mock_generate.return_value = SAMPLE_ROWS
        wizard = self._make_wizard()
        action = wizard.action_generate()
        exam = self.env['bxi.exam'].browse(action['res_id'])
        self.assertEqual(exam.source, 'ai')
        self.assertEqual(exam.state, 'draft')
        self.assertEqual(len(exam.question_ids), 2)
        mcq = exam.question_ids.filtered(lambda q: q.question_type == 'mcq')
        self.assertEqual(len(mcq.option_ids), 2)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.BxiAiClient.generate_questions')
    def test_regenerate_replaces_existing_questions(self, mock_generate):
        mock_generate.return_value = SAMPLE_ROWS
        wizard = self._make_wizard()
        action = wizard.action_generate()
        exam = self.env['bxi.exam'].browse(action['res_id'])
        old_question_ids = set(exam.question_ids.ids)

        mock_generate.return_value = SAMPLE_ROWS[:1]
        wizard2 = self._make_wizard(exam_id=exam.id)
        wizard2.action_generate()
        exam.invalidate_recordset()
        self.assertEqual(len(exam.question_ids), 1)
        self.assertFalse(set(exam.question_ids.ids) & old_question_ids)

    def test_question_count_bounds(self):
        with self.assertRaises(UserError):
            self._make_wizard(question_count=0)
