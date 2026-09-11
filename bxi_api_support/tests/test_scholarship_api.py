# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportScholarship(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scholarship_staff_user = mail_new_test_user(
            cls.env, login='scholarship_api_staff',
            groups='base.group_user,bxi_school_scholarship.group_scholarship_staff',
            password='ScholarStaffPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='scholarship_api_other', groups='base.group_user', password='OtherPass1!')
        cls.student_user = mail_new_test_user(
            cls.env, login='scholarship_api_student', groups='base.group_user', password='StudentPass1!')
        cls.student = cls._create_student('SCHAPI-001', user=cls.student_user)
        cls.academic_year = cls.env['op.academic.year'].create({
            'name': 'API Support AY',
            'start_date': fields.Date.today(), 'end_date': fields.Date.today() + timedelta(days=300),
        })

    def _create_scholarship(self):
        staff_headers = self._headers('scholarship_api_staff', 'ScholarStaffPass1!')
        return self.url_open('/api/v1/scholarships', headers=staff_headers, json={
            'student_id': self.student.id, 'scholarship_type': 'merit',
            'academic_year_id': self.academic_year.id, 'coverage_type': 'fixed_amount',
            'fixed_amount': 500.0, 'valid_until': (fields.Date.today() + timedelta(days=200)).isoformat(),
        })

    def test_scholarships_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/scholarships').status_code, 401)

    def test_only_staff_can_create_scholarship(self):
        resp = self.url_open('/api/v1/scholarships', headers=self._headers('scholarship_api_other', 'OtherPass1!'), json={
            'student_id': self.student.id, 'academic_year_id': self.academic_year.id,
            'valid_until': fields.Date.today().isoformat(),
        })
        self.assertEqual(resp.status_code, 403)

    def test_staff_can_create_scholarship(self):
        resp = self._create_scholarship()
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['data']['approval_status'], 'draft')

    def test_create_missing_valid_until_rejected(self):
        staff_headers = self._headers('scholarship_api_staff', 'ScholarStaffPass1!')
        resp = self.url_open('/api/v1/scholarships', headers=staff_headers, json={
            'student_id': self.student.id, 'academic_year_id': self.academic_year.id,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_valid_until')

    def test_full_approval_lifecycle(self):
        scholarship_id = self._create_scholarship().json()['data']['id']
        staff_headers = self._headers('scholarship_api_staff', 'ScholarStaffPass1!')

        submit = self.url_open(f'/api/v1/scholarships/{scholarship_id}/submit', headers=staff_headers, method='POST')
        self.assertEqual(submit.status_code, 200)
        self.assertEqual(submit.json()['data']['approval_status'], 'pending')

        approve = self.url_open(f'/api/v1/scholarships/{scholarship_id}/approve', headers=staff_headers, method='POST')
        self.assertEqual(approve.status_code, 200)
        self.assertEqual(approve.json()['data']['approval_status'], 'approved')

        reset = self.url_open(f'/api/v1/scholarships/{scholarship_id}/reset', headers=staff_headers, method='POST')
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset.json()['data']['approval_status'], 'draft')

    def test_student_can_view_own_scholarship(self):
        scholarship_id = self._create_scholarship().json()['data']['id']
        resp = self.url_open(
            f'/api/v1/scholarships/{scholarship_id}', headers=self._headers('scholarship_api_student', 'StudentPass1!'))
        self.assertEqual(resp.status_code, 200)

    def test_unrelated_user_cannot_view_scholarship(self):
        scholarship_id = self._create_scholarship().json()['data']['id']
        resp = self.url_open(
            f'/api/v1/scholarships/{scholarship_id}', headers=self._headers('scholarship_api_other', 'OtherPass1!'))
        self.assertEqual(resp.status_code, 403)
