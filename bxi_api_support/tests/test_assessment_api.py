# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportAssessment(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.teacher_user = mail_new_test_user(
            cls.env, login='assess_api_teacher', groups='base.group_user,openeducat_core.group_op_faculty',
            password='TeacherPass1!')
        cls.other_teacher_user = mail_new_test_user(
            cls.env, login='assess_api_other_teacher', groups='base.group_user,openeducat_core.group_op_faculty',
            password='OtherTeacherPass1!')
        cls.coordinator_user = mail_new_test_user(
            cls.env, login='assess_api_coordinator',
            groups='base.group_user,bxi_academic_management.group_academic_coordinator',
            password='CoordPass1!')
        cls.course = cls.env['op.course'].create({'name': 'Assess API Course', 'code': 'ASS-C1'})
        cls.subject = cls.env['op.subject'].create({'name': 'Assess API Subject', 'code': 'ASS-S1'})
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Assess', 'last_name': 'Teacher', 'gender': 'male',
            'birth_date': '1985-01-01', 'user_id': cls.teacher_user.id,
        })
        cls.other_faculty = cls.env['op.faculty'].create({
            'first_name': 'Other', 'last_name': 'Teacher', 'gender': 'female',
            'birth_date': '1986-01-01', 'user_id': cls.other_teacher_user.id,
        })
        cls.student = cls._create_student('ASSAPI-001')

    def _teacher_headers(self):
        return self._headers('assess_api_teacher', 'TeacherPass1!')

    def _create_exam(self):
        resp = self.url_open('/api/v1/assessments/exams', headers=self._teacher_headers(), json={
            'name': 'API Exam 1', 'class_id': self.course.id, 'subject_id': self.subject.id,
        })
        return resp.json()['data']

    def test_exams_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/assessments/exams').status_code, 401)

    def test_teacher_can_create_exam(self):
        exam = self._create_exam()
        self.assertEqual(exam['state'], 'draft')
        self.assertEqual(exam['teacher'], self.faculty.display_name)

    def test_publish_requires_questions(self):
        exam = self._create_exam()
        resp = self.url_open(
            f'/api/v1/assessments/exams/{exam["id"]}/publish', headers=self._teacher_headers(), method='POST')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_transition')

    def test_other_teacher_cannot_publish(self):
        exam = self._create_exam()
        resp = self.url_open(
            f'/api/v1/assessments/exams/{exam["id"]}/publish',
            headers=self._headers('assess_api_other_teacher', 'OtherTeacherPass1!'), method='POST')
        self.assertEqual(resp.status_code, 403)

    def test_full_exam_session_submission_grading_flow(self):
        exam = self._create_exam()
        exam_record = self.env['bxi.exam'].sudo().browse(exam['id'])
        question = self.env['bxi.exam.question'].sudo().create({
            'exam_id': exam_record.id, 'question_type': 'mcq', 'question_text': 'What is 2+2?', 'marks': 5,
        })
        correct_option = self.env['bxi.exam.question.option'].sudo().create({
            'question_id': question.id, 'option_text': '4', 'is_correct': True,
        })
        self.env['bxi.exam.question.option'].sudo().create({
            'question_id': question.id, 'option_text': '5', 'is_correct': False,
        })

        headers = self._teacher_headers()
        publish = self.url_open(f'/api/v1/assessments/exams/{exam["id"]}/publish', headers=headers, method='POST')
        self.assertEqual(publish.status_code, 200)
        self.assertEqual(publish.json()['data']['state'], 'published')

        session_resp = self.url_open('/api/v1/assessments/sessions', headers=headers, json={
            'exam_id': exam['id'], 'class_id': self.course.id, 'student_ids': [self.student.id],
        })
        self.assertEqual(session_resp.status_code, 201)
        session = session_resp.json()['data']
        self.assertEqual(session['submission_count'], 1)

        submissions = self.url_open(
            f'/api/v1/assessments/submissions?session_id={session["id"]}', headers=headers).json()['data']['submissions']
        self.assertEqual(len(submissions), 1)
        submission_id = submissions[0]['id']

        answer_resp = self.url_open(
            f'/api/v1/assessments/submissions/{submission_id}/answers', headers=headers, json={
                'answers': [{'question_id': question.id, 'selected_option_id': correct_option.id}],
            })
        self.assertEqual(answer_resp.status_code, 200)

        mark_resp = self.url_open(
            f'/api/v1/assessments/submissions/{submission_id}/mark-submitted', headers=headers, method='POST')
        self.assertEqual(mark_resp.status_code, 200)
        self.assertEqual(mark_resp.json()['data']['status'], 'submitted')

        grade_resp = self.url_open(
            f'/api/v1/assessments/submissions/{submission_id}/auto-grade', headers=headers, method='POST')
        self.assertEqual(grade_resp.status_code, 200)
        self.assertEqual(grade_resp.json()['data']['status'], 'auto_graded')
        self.assertEqual(grade_resp.json()['data']['total_score'], 5.0)

    def test_cancel_session_requires_ownership(self):
        exam = self._create_exam()
        headers = self._teacher_headers()
        session = self.url_open('/api/v1/assessments/sessions', headers=headers, json={
            'exam_id': exam['id'], 'class_id': self.course.id, 'student_ids': [self.student.id],
        }).json()['data']

        resp = self.url_open(
            f'/api/v1/assessments/sessions/{session["id"]}/cancel',
            headers=self._headers('assess_api_other_teacher', 'OtherTeacherPass1!'), method='POST')
        self.assertEqual(resp.status_code, 403)

        resp = self.url_open(f'/api/v1/assessments/sessions/{session["id"]}/cancel', headers=headers, method='POST')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['state'], 'cancelled')

    def test_coordinator_sees_all_exams(self):
        self._create_exam()
        resp = self.url_open('/api/v1/assessments/exams', headers=self._headers('assess_api_coordinator', 'CoordPass1!'))
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()['meta']['total'], 1)
