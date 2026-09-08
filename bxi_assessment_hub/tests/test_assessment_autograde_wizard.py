# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAssessmentAutogradeWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({'name': 'Class 6', 'code': 'AG6'})
        cls.subject = cls.env['op.subject'].create({'name': 'Math', 'code': 'AGMATH'})
        cls.teacher = cls.env['op.faculty'].create({
            'first_name': 'Neha', 'last_name': 'Kapoor', 'birth_date': '1982-01-01', 'gender': 'female',
        })
        cls.exam = cls.env['bxi.exam'].create({
            'name': 'Math Test', 'class_id': cls.course.id, 'subject_id': cls.subject.id,
            'teacher_id': cls.teacher.id,
        })
        cls.env['bxi.exam.question'].create({
            'exam_id': cls.exam.id, 'question_type': 'short_answer',
            'question_text': 'What is 2+2?', 'marks': 2, 'sample_answer_keywords': 'four',
        })
        cls.exam.action_publish()

        cls.student1 = cls.env['op.student'].create({'first_name': 'C', 'last_name': 'One', 'gender': 'm'})
        cls.student2 = cls.env['op.student'].create({'first_name': 'D', 'last_name': 'Two', 'gender': 'f'})
        cls.session = cls.env['bxi.assessment.session'].create({
            'exam_id': cls.exam.id, 'class_id': cls.course.id, 'teacher_id': cls.teacher.id,
            'exam_date': '2026-10-01', 'exam_time': 9.0,
            'student_ids': [(6, 0, [cls.student1.id, cls.student2.id])],
        })

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('bxi_assessment_hub.anthropic_api_key', 'test-key')
        for submission in self.session.submission_ids:
            submission.answer_ids.student_answer_text = 'four'
            submission.action_mark_submitted()

    def test_raises_when_not_configured(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_assessment_hub.anthropic_api_key', False)
        wizard = self.env['bxi.assessment.autograde.wizard'].create({
            'submission_ids': [(6, 0, self.session.submission_ids.ids)],
        })
        with self.assertRaises(UserError):
            wizard.action_start_grading()

    def test_raises_when_no_pending_submissions(self):
        wizard = self.env['bxi.assessment.autograde.wizard'].create({'submission_ids': [(5, 0, 0)]})
        with self.assertRaises(UserError):
            wizard.action_start_grading()

    def test_default_picks_up_all_submitted(self):
        # Asserts the fixture's own submissions are included, not an exact
        # count - other 'submitted' records may already exist in the
        # database (e.g. real usage data), and the wizard is meant to pick
        # up every pending submission system-wide, not just these two.
        wizard = self.env['bxi.assessment.autograde.wizard'].create({})
        self.assertTrue(set(self.session.submission_ids.ids) <= set(wizard.submission_ids.ids))

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.BxiAiClient.grade_answer')
    def test_start_grading_grades_all_and_reports_counts(self, mock_grade):
        mock_grade.return_value = {'awarded_marks': 2.0, 'rationale': ''}
        wizard = self.env['bxi.assessment.autograde.wizard'].create({
            'submission_ids': [(6, 0, self.session.submission_ids.ids)],
        })
        wizard.action_start_grading()
        self.assertEqual(wizard.state, 'done')
        self.assertEqual(wizard.graded_count, 2)
        self.assertEqual(wizard.failed_count, 0)
        for submission in self.session.submission_ids:
            self.assertEqual(submission.status, 'auto_graded')
            self.assertEqual(submission.total_score, 2.0)
