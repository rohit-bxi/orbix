# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAssessmentSession(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({'name': 'Class 9', 'code': 'SESS9'})
        cls.subject = cls.env['op.subject'].create({'name': 'Biology', 'code': 'SESSBIO'})
        cls.teacher = cls.env['op.faculty'].create({
            'first_name': 'Meena', 'last_name': 'Iyer', 'birth_date': '1985-01-01', 'gender': 'female',
        })
        cls.exam = cls.env['bxi.exam'].create({
            'name': 'Biology Test', 'class_id': cls.course.id, 'subject_id': cls.subject.id,
            'teacher_id': cls.teacher.id,
        })
        cls.env['bxi.exam.question'].create({
            'exam_id': cls.exam.id, 'question_type': 'short_answer',
            'question_text': 'Define photosynthesis', 'marks': 5,
        })
        cls.exam.action_publish()

        cls.student1 = cls.env['op.student'].create({'first_name': 'A', 'last_name': 'One', 'gender': 'm'})
        cls.student2 = cls.env['op.student'].create({'first_name': 'B', 'last_name': 'Two', 'gender': 'f'})
        cls.env['op.student.course'].create({
            'student_id': cls.student1.id, 'course_id': cls.course.id, 'state': 'running',
        })
        cls.env['op.student.course'].create({
            'student_id': cls.student2.id, 'course_id': cls.course.id, 'state': 'running',
        })

    def _make_session(self, **overrides):
        vals = {
            'exam_id': self.exam.id, 'class_id': self.course.id, 'teacher_id': self.teacher.id,
            'exam_date': '2026-10-01', 'exam_time': 9.5,
            'student_ids': [(6, 0, [self.student1.id, self.student2.id])],
        }
        vals.update(overrides)
        return self.env['bxi.assessment.session'].create(vals)

    def test_create_seeds_submissions_and_answers(self):
        session = self._make_session()
        self.assertEqual(len(session.submission_ids), 2)
        for submission in session.submission_ids:
            self.assertEqual(len(submission.answer_ids), 1)
            self.assertEqual(submission.status, 'not_submitted')

    def test_total_marks_related(self):
        session = self._make_session()
        self.assertEqual(session.total_marks, 5)

    def test_assignment_summary(self):
        session = self._make_session()
        self.assertIn('1 question(s)', session.assignment_summary)
        self.assertIn('2 student(s) selected', session.assignment_summary)

    def test_onchange_class_id_populates_students(self):
        session = self.env['bxi.assessment.session'].new({
            'exam_id': self.exam.id, 'class_id': self.course.id,
        })
        session._onchange_class_id()
        self.assertEqual(set(session.student_ids.ids), {self.student1.id, self.student2.id})

    def test_action_cancel(self):
        session = self._make_session()
        session.action_cancel()
        self.assertEqual(session.state, 'cancelled')
