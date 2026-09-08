# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestExam(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({'name': 'Class 10', 'code': 'C10'})
        cls.subject = cls.env['op.subject'].create({'name': 'Physics', 'code': 'PHY'})
        cls.teacher = cls.env['op.faculty'].create({
            'first_name': 'Rakesh', 'last_name': 'Gehlot',
            'birth_date': '1985-05-05', 'gender': 'male',
        })

    def _make_exam(self, **overrides):
        vals = {
            'name': 'Physics MCQ Test',
            'class_id': self.course.id,
            'subject_id': self.subject.id,
            'teacher_id': self.teacher.id,
            'duration': 45,
        }
        vals.update(overrides)
        return self.env['bxi.exam'].create(vals)

    def _add_short_answer_question(self, exam, marks=5):
        return self.env['bxi.exam.question'].create({
            'exam_id': exam.id,
            'question_type': 'short_answer',
            'question_text': "State Newton's Third Law of Motion",
            'marks': marks,
            'sample_answer_keywords': 'action, reaction, equal, opposite',
        })

    def _add_mcq_question(self, exam, correct_index=0, marks=1):
        question = self.env['bxi.exam.question'].create({
            'exam_id': exam.id,
            'question_type': 'mcq',
            'question_text': "Who formulated the laws of motion?",
            'marks': marks,
        })
        options = ['Newton', 'Jonas', 'Frost']
        for i, text in enumerate(options):
            self.env['bxi.exam.question.option'].create({
                'question_id': question.id,
                'option_text': text,
                'is_correct': i == correct_index,
            })
        return question

    # --- defaults and computed fields ---

    def test_default_state_draft(self):
        exam = self._make_exam()
        self.assertEqual(exam.state, 'draft')
        self.assertEqual(exam.source, 'manual')

    def test_question_stats_computed(self):
        exam = self._make_exam()
        self._add_short_answer_question(exam, marks=5)
        self._add_mcq_question(exam, marks=1)
        self.assertEqual(exam.question_count, 2)
        self.assertEqual(exam.total_marks, 6)

    def test_default_teacher_from_current_user(self):
        teacher_for_user = self.env['op.faculty'].create({
            'first_name': 'Self', 'last_name': 'Teacher',
            'birth_date': '1990-01-01', 'gender': 'male',
            'user_id': self.env.uid,
        })
        exam = self.env['bxi.exam'].create({
            'name': 'Auto Teacher Exam',
            'class_id': self.course.id,
            'subject_id': self.subject.id,
        })
        self.assertEqual(exam.teacher_id, teacher_for_user)

    # --- MCQ option label ---

    def test_mcq_option_labels_lettered_in_order(self):
        exam = self._make_exam()
        question = self._add_mcq_question(exam, correct_index=0)
        labels = question.option_ids.sorted('sequence').mapped('label')
        self.assertEqual(labels, ['A', 'B', 'C'])

    # --- MCQ building and validation ---

    def test_mcq_question_can_be_built_incrementally(self):
        # A question is created first, then its options one at a time (the
        # same pattern the AI assignment generator will use) - this must
        # not raise even though the question briefly has zero/one options.
        exam = self._make_exam()
        question = self.env['bxi.exam.question'].create({
            'exam_id': exam.id, 'question_type': 'mcq',
            'question_text': 'Pick one', 'marks': 1,
        })
        self.env['bxi.exam.question.option'].create({
            'question_id': question.id, 'option_text': 'Only Option', 'is_correct': True,
        })
        self.assertEqual(len(question.option_ids), 1)

    def test_mcq_valid_with_one_correct_option(self):
        exam = self._make_exam()
        question = self._add_mcq_question(exam, correct_index=1)
        self.assertTrue(question.id)
        self.assertEqual(len(question.option_ids.filtered('is_correct')), 1)
        self.assertFalse(question._mcq_publish_error())

    def test_mcq_publish_error_when_too_few_options(self):
        exam = self._make_exam()
        question = self.env['bxi.exam.question'].create({
            'exam_id': exam.id, 'question_type': 'mcq',
            'question_text': 'Pick one', 'marks': 1,
        })
        self.env['bxi.exam.question.option'].create({
            'question_id': question.id, 'option_text': 'Only Option', 'is_correct': True,
        })
        self.assertTrue(question._mcq_publish_error())
        with self.assertRaises(UserError):
            exam.action_publish()

    def test_mcq_publish_error_when_no_correct_option(self):
        exam = self._make_exam()
        question = self.env['bxi.exam.question'].create({
            'exam_id': exam.id, 'question_type': 'mcq',
            'question_text': 'Pick one', 'marks': 1,
        })
        self.env['bxi.exam.question.option'].create([
            {'question_id': question.id, 'option_text': 'Option A', 'is_correct': False},
            {'question_id': question.id, 'option_text': 'Option B', 'is_correct': False},
        ])
        self.assertTrue(question._mcq_publish_error())
        with self.assertRaises(UserError):
            exam.action_publish()

    def test_publish_succeeds_with_valid_mcq(self):
        exam = self._make_exam()
        self._add_mcq_question(exam, correct_index=0)
        exam.action_publish()
        self.assertEqual(exam.state, 'published')

    def test_short_answer_question_not_subject_to_mcq_constraint(self):
        exam = self._make_exam()
        question = self._add_short_answer_question(exam)
        self.assertTrue(question.id)
        self.assertFalse(question.option_ids)

    # --- publish workflow ---

    def test_publish_requires_at_least_one_question(self):
        exam = self._make_exam()
        with self.assertRaises(UserError):
            exam.action_publish()

    def test_publish_succeeds_with_questions(self):
        exam = self._make_exam()
        self._add_short_answer_question(exam)
        exam.action_publish()
        self.assertEqual(exam.state, 'published')

    def test_reset_to_draft(self):
        exam = self._make_exam()
        self._add_short_answer_question(exam)
        exam.action_publish()
        exam.action_reset_to_draft()
        self.assertEqual(exam.state, 'draft')
