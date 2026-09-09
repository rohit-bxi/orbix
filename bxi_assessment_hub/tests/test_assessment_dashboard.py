# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAssessmentDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({'name': 'Class 10', 'code': 'DASHC10'})
        cls.subject = cls.env['op.subject'].create({'name': 'Mathematics', 'code': 'DASHMATH'})
        cls.teacher = cls.env['op.faculty'].create({
            'first_name': 'Dash', 'last_name': 'Teacher', 'birth_date': '1985-01-01', 'gender': 'female',
        })
        cls.exam = cls.env['bxi.exam'].create({
            'name': 'Dashboard Mid-Term', 'class_id': cls.course.id, 'subject_id': cls.subject.id,
            'teacher_id': cls.teacher.id,
        })
        cls.env['bxi.exam.question'].create({
            'exam_id': cls.exam.id, 'question_type': 'short_answer',
            'question_text': 'Define a prime number', 'marks': 10,
        })
        cls.exam.action_publish()

        cls.student = cls.env['op.student'].create({'first_name': 'Dash', 'last_name': 'Student', 'gender': 'm'})
        cls.env['op.student.course'].create({
            'student_id': cls.student.id, 'course_id': cls.course.id, 'state': 'running',
        })
        cls.session = cls.env['bxi.assessment.session'].create({
            'exam_id': cls.exam.id, 'class_id': cls.course.id, 'teacher_id': cls.teacher.id,
            'exam_date': '2020-01-01', 'exam_time': 9.0,
            'student_ids': [(6, 0, [cls.student.id])],
        })
        cls.submission = cls.session.submission_ids

    def test_get_dashboard_data_structure(self):
        data = self.env['bxi.assessment.dashboard'].get_dashboard_data()
        self.assertEqual(
            {'total_exams_scheduled', 'assessments_defined', 'evaluation_in_progress', 'results_locked'},
            set(data['kpis'].keys()))
        self.assertEqual(
            {'pending_evaluations', 'upcoming_exams', 'unlinked_exams'}, set(data['alerts'].keys()))
        self.assertIn('recent_exams', data)
        self.assertIn('performance_by_class', data)

    def test_unlinked_exam_count_drops_once_linked(self):
        before = self.env['bxi.assessment.dashboard'].get_dashboard_data()['alerts']['unlinked_exams']['count']
        self.assertGreaterEqual(before, 1)
        self.exam.curriculum_id = self.env['bxi.curriculum'].create({
            'name': 'Dashboard Curriculum', 'board_id': self.env['bxi.board'].create({'name': 'DashBoard'}).id,
            'description': 'test',
        }).id
        after = self.env['bxi.assessment.dashboard'].get_dashboard_data()['alerts']['unlinked_exams']['count']
        self.assertEqual(after, before - 1)

    def test_recent_exam_status_completed_when_reviewed(self):
        self.submission.answer_ids.write({'student_answer_text': 'A prime number has two factors'})
        self.submission.action_mark_submitted()
        self.submission.write({'status': 'reviewed'})
        data = self.env['bxi.assessment.dashboard'].get_dashboard_data()
        card = next(c for c in data['recent_exams'] if c['id'] == self.session.id)
        self.assertEqual(card['status'], 'completed')

    def test_recent_exam_status_evaluating_when_pending(self):
        self.submission.answer_ids.write({'student_answer_text': 'A prime number has two factors'})
        self.submission.action_mark_submitted()
        data = self.env['bxi.assessment.dashboard'].get_dashboard_data()
        card = next(c for c in data['recent_exams'] if c['id'] == self.session.id)
        self.assertEqual(card['status'], 'evaluating')

    def test_performance_by_class_uses_reviewed_only(self):
        self.submission.write({'status': 'reviewed', 'manual_adjustment': 10.0})
        data = self.env['bxi.assessment.dashboard'].get_dashboard_data()
        self.assertIn(self.course.name, data['performance_by_class']['labels'])
