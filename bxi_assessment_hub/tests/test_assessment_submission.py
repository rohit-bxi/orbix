# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAssessmentSubmission(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({'name': 'Class 7', 'code': 'SUB7'})
        cls.subject = cls.env['op.subject'].create({'name': 'English', 'code': 'SUBENG'})
        cls.teacher = cls.env['op.faculty'].create({
            'first_name': 'Ravi', 'last_name': 'Shetty', 'birth_date': '1980-01-01', 'gender': 'male',
        })
        cls.exam = cls.env['bxi.exam'].create({
            'name': 'English Test', 'class_id': cls.course.id, 'subject_id': cls.subject.id,
            'teacher_id': cls.teacher.id,
        })
        cls.short_question = cls.env['bxi.exam.question'].create({
            'exam_id': cls.exam.id, 'question_type': 'short_answer',
            'question_text': 'Define noun', 'marks': 5, 'sample_answer_keywords': 'naming word',
        })
        cls.mcq_question = cls.env['bxi.exam.question'].create({
            'exam_id': cls.exam.id, 'question_type': 'mcq', 'question_text': 'Pick the noun', 'marks': 1,
        })
        cls.correct_option = cls.env['bxi.exam.question.option'].create({
            'question_id': cls.mcq_question.id, 'option_text': 'Dog', 'is_correct': True,
        })
        cls.wrong_option = cls.env['bxi.exam.question.option'].create({
            'question_id': cls.mcq_question.id, 'option_text': 'Run', 'is_correct': False,
        })
        cls.exam.action_publish()

        cls.student = cls.env['op.student'].create({'first_name': 'S', 'last_name': 'One', 'gender': 'm'})
        cls.session = cls.env['bxi.assessment.session'].create({
            'exam_id': cls.exam.id, 'class_id': cls.course.id, 'teacher_id': cls.teacher.id,
            'exam_date': '2026-10-01', 'exam_time': 9.0,
            'student_ids': [(6, 0, [cls.student.id])],
        })
        cls.submission = cls.session.submission_ids

    def _fill_answers(self, short_text='A naming word.', option=None):
        short_answer = self.submission.answer_ids.filtered(lambda a: a.question_id == self.short_question)
        mcq_answer = self.submission.answer_ids.filtered(lambda a: a.question_id == self.mcq_question)
        short_answer.student_answer_text = short_text
        mcq_answer.selected_option_id = option or self.correct_option

    def test_mark_submitted_requires_all_answers(self):
        with self.assertRaises(UserError):
            self.submission.action_mark_submitted()

    def test_mark_submitted_succeeds_when_complete(self):
        self._fill_answers()
        self.submission.action_mark_submitted()
        self.assertEqual(self.submission.status, 'submitted')
        self.assertTrue(self.submission.submitted_at)

    def test_auto_grade_requires_submitted_status(self):
        with self.assertRaises(UserError):
            self.submission.action_auto_grade()

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.BxiAiClient.grade_answer')
    def test_auto_grade_scores_mcq_and_ai_grades_short_answer(self, mock_grade):
        mock_grade.return_value = {'awarded_marks': 4.0, 'rationale': 'Mostly correct'}
        self._fill_answers()
        self.submission.action_mark_submitted()
        self.submission.action_auto_grade()

        self.assertEqual(self.submission.status, 'auto_graded')
        mcq_answer = self.submission.answer_ids.filtered(lambda a: a.question_id == self.mcq_question)
        short_answer = self.submission.answer_ids.filtered(lambda a: a.question_id == self.short_question)
        self.assertEqual(mcq_answer.awarded_marks, 1.0)
        self.assertFalse(mcq_answer.is_ai_graded)
        self.assertEqual(short_answer.awarded_marks, 4.0)
        self.assertTrue(short_answer.is_ai_graded)
        self.assertEqual(self.submission.total_score, 5.0)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.BxiAiClient.grade_answer')
    def test_auto_grade_mcq_wrong_option_scores_zero(self, mock_grade):
        mock_grade.return_value = {'awarded_marks': 0.0, 'rationale': ''}
        self._fill_answers(option=self.wrong_option)
        self.submission.action_mark_submitted()
        self.submission.action_auto_grade()
        mcq_answer = self.submission.answer_ids.filtered(lambda a: a.question_id == self.mcq_question)
        self.assertEqual(mcq_answer.awarded_marks, 0.0)

    def test_total_score_clamped_to_max(self):
        self.submission.manual_adjustment = 1000
        self.assertEqual(self.submission.total_score, self.submission.max_score)

    def test_total_score_never_negative(self):
        self.submission.manual_adjustment = -1000
        self.assertEqual(self.submission.total_score, 0.0)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.BxiAiClient.grade_answer')
    def test_reevaluation_wizard_applies_adjustment_and_logs(self, mock_grade):
        mock_grade.return_value = {'awarded_marks': 3.0, 'rationale': ''}
        self._fill_answers()
        self.submission.action_mark_submitted()
        self.submission.action_auto_grade()
        original_score = self.submission.total_score
        message_count_before = len(self.submission.message_ids)

        wizard = self.env['bxi.assessment.reevaluation.wizard'].create({
            'submission_id': self.submission.id, 'marks_adjustment': 1.5, 'reason': 'Manual bonus',
        })
        self.assertEqual(wizard.estimated_new_score, min(original_score + 1.5, self.submission.max_score))
        wizard.action_confirm()

        self.assertEqual(self.submission.status, 'reviewed')
        self.assertEqual(self.submission.reevaluation_reason, 'Manual bonus')
        self.assertGreater(len(self.submission.message_ids), message_count_before)
