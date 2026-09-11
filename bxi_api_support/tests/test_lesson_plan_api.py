# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportLessonPlan(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.teacher_user = mail_new_test_user(
            cls.env, login='lp_api_teacher', groups='base.group_user,openeducat_core.group_op_faculty',
            password='TeacherPass1!')
        cls.other_teacher_user = mail_new_test_user(
            cls.env, login='lp_api_other_teacher', groups='base.group_user,openeducat_core.group_op_faculty',
            password='OtherTeacherPass1!')
        cls.coordinator_user = mail_new_test_user(
            cls.env, login='lp_api_coordinator',
            groups='base.group_user,bxi_academic_management.group_academic_coordinator',
            password='CoordPass1!')
        cls.course = cls.env['op.course'].create({'name': 'LP API Course', 'code': 'LP-C1'})
        cls.subject = cls.env['op.subject'].create({'name': 'LP API Subject', 'code': 'LP-S1'})
        cls.academic_year = cls.env['op.academic.year'].create({
            'name': 'LP API AY', 'start_date': '2026-06-01', 'end_date': '2027-03-31',
        })
        cls.term = cls.env['op.academic.term'].create({
            'name': 'LP API Term', 'term_start_date': '2026-06-01', 'term_end_date': '2026-10-31',
            'academic_year_id': cls.academic_year.id,
        })
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'LP', 'last_name': 'Teacher', 'gender': 'male',
            'birth_date': '1985-01-01', 'user_id': cls.teacher_user.id,
        })

    def _create_plan(self):
        return self.url_open('/api/v1/lesson-plans', headers=self._headers('lp_api_teacher', 'TeacherPass1!'), json={
            'subject_id': self.subject.id, 'class_id': self.course.id, 'quarter_id': self.term.id,
            'topic': 'Fractions', 'objective': 'Understand fractions', 'activities': 'Group work',
            'resources': 'Textbook', 'assessment_method': 'Quiz',
            'start_date': '2026-07-01', 'end_date': '2026-07-05', 'plan_date': '2026-07-01',
        })

    def test_plans_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/lesson-plans').status_code, 401)

    def test_teacher_can_create_plan(self):
        resp = self._create_plan()
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['data']['state'], 'pending')

    def test_create_plan_missing_fields_rejected(self):
        resp = self.url_open('/api/v1/lesson-plans', headers=self._headers('lp_api_teacher', 'TeacherPass1!'), json={
            'subject_id': self.subject.id,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_fields')

    def test_coordinator_can_review_reject_then_teacher_resubmits(self):
        plan_id = self._create_plan().json()['data']['id']
        coord_headers = self._headers('lp_api_coordinator', 'CoordPass1!')

        review = self.url_open(f'/api/v1/lesson-plans/{plan_id}/review', headers=coord_headers, json={
            'decision': 'rejected', 'feedback': 'Add more activities.',
        })
        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json()['data']['state'], 'rejected')

        resubmit = self.url_open(
            f'/api/v1/lesson-plans/{plan_id}/resubmit',
            headers=self._headers('lp_api_teacher', 'TeacherPass1!'), method='POST')
        self.assertEqual(resubmit.status_code, 200)
        self.assertEqual(resubmit.json()['data']['state'], 'pending')

    def test_teacher_cannot_review(self):
        plan_id = self._create_plan().json()['data']['id']
        resp = self.url_open(
            f'/api/v1/lesson-plans/{plan_id}/review',
            headers=self._headers('lp_api_teacher', 'TeacherPass1!'), json={'decision': 'approved'})
        self.assertEqual(resp.status_code, 403)

    def test_other_teacher_cannot_view_plan(self):
        plan_id = self._create_plan().json()['data']['id']
        resp = self.url_open(
            f'/api/v1/lesson-plans/{plan_id}',
            headers=self._headers('lp_api_other_teacher', 'OtherTeacherPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_invalid_decision_rejected(self):
        plan_id = self._create_plan().json()['data']['id']
        resp = self.url_open(
            f'/api/v1/lesson-plans/{plan_id}/review',
            headers=self._headers('lp_api_coordinator', 'CoordPass1!'), json={'decision': 'maybe'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_decision')
