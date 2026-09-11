# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportOnboarding(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.faculty_user = mail_new_test_user(
            cls.env, login='onboard_api_faculty', groups='base.group_user,openeducat_core.group_op_faculty',
            password='FacultyPass1!')
        cls.other_faculty_user = mail_new_test_user(
            cls.env, login='onboard_api_other_faculty', groups='base.group_user,openeducat_core.group_op_faculty',
            password='OtherFacultyPass1!')
        cls.admin_user = mail_new_test_user(
            cls.env, login='onboard_api_admin',
            groups='base.group_user,openeducat_core.group_op_back_office_admin',
            password='AdminPass1!')
        cls.plain_user = mail_new_test_user(
            cls.env, login='onboard_api_plain', groups='base.group_user', password='PlainPass1!')
        cls.course = cls.env['op.course'].create({'name': 'Onboard API Course', 'code': 'OB-C1'})
        cls.batch = cls.env['op.batch'].create({
            'name': 'Onboard API Batch', 'code': 'OB-B1', 'course_id': cls.course.id,
            'start_date': '2026-06-01', 'end_date': '2027-03-31',
        })

    def _faculty_headers(self):
        return self._headers('onboard_api_faculty', 'FacultyPass1!')

    def test_onboarding_requires_auth(self):
        self.assertEqual(self.url_open('/api/v1/onboarding').status_code, 401)

    def test_plain_user_cannot_start_onboarding(self):
        resp = self.url_open('/api/v1/onboarding', headers=self._headers('onboard_api_plain', 'PlainPass1!'), json={}, method='POST')
        self.assertEqual(resp.status_code, 403)

    def test_next_without_required_fields_rejected(self):
        headers = self._faculty_headers()
        create = self.url_open('/api/v1/onboarding', headers=headers, json={}, method='POST')
        self.assertEqual(create.status_code, 201)
        onboarding_id = create.json()['data']['id']

        resp = self.url_open(f'/api/v1/onboarding/{onboarding_id}/next', headers=headers, method='POST')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_transition')

    def test_full_onboarding_flow_creates_student(self):
        headers = self._faculty_headers()
        onboarding_id = self.url_open('/api/v1/onboarding', headers=headers, json={}, method='POST').json()['data']['id']

        update1 = self.url_open(f'/api/v1/onboarding/{onboarding_id}/update', headers=headers, json={
            'full_name': 'Jordan Onboard Test', 'gender': 'm', 'birth_date': '2015-05-05',
            'email': 'jordan.onboard@example.com',
        })
        self.assertEqual(update1.status_code, 200)

        next1 = self.url_open(f'/api/v1/onboarding/{onboarding_id}/next', headers=headers, method='POST')
        self.assertEqual(next1.status_code, 200)
        self.assertEqual(next1.json()['data']['state'], 'academic_info')

        update2 = self.url_open(f'/api/v1/onboarding/{onboarding_id}/update', headers=headers, json={
            'admission_number': 'OB-ADM-001', 'admission_date': '2026-06-01',
            'course_id': self.course.id, 'batch_id': self.batch.id, 'enrollment_status': 'new_admission',
        })
        self.assertEqual(update2.status_code, 200)

        next2 = self.url_open(f'/api/v1/onboarding/{onboarding_id}/next', headers=headers, method='POST')
        self.assertEqual(next2.status_code, 200)
        self.assertEqual(next2.json()['data']['state'], 'documents')

        complete = self.url_open(f'/api/v1/onboarding/{onboarding_id}/complete', headers=headers, method='POST')
        self.assertEqual(complete.status_code, 200)
        self.assertEqual(complete.json()['data']['state'], 'done')
        self.assertTrue(complete.json()['data']['student_id'])

        student = self.env['op.student'].sudo().browse(complete.json()['data']['student_id'])
        self.assertEqual(student.first_name, 'Jordan')
        self.assertEqual(student.gr_no, 'OB-ADM-001')

    def test_complete_before_documents_step_rejected(self):
        headers = self._faculty_headers()
        onboarding_id = self.url_open('/api/v1/onboarding', headers=headers, json={}, method='POST').json()['data']['id']
        resp = self.url_open(f'/api/v1/onboarding/{onboarding_id}/complete', headers=headers, method='POST')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_transition')

    def test_other_faculty_cannot_view_record_they_did_not_create(self):
        headers = self._faculty_headers()
        onboarding_id = self.url_open('/api/v1/onboarding', headers=headers, json={}, method='POST').json()['data']['id']

        resp = self.url_open(
            f'/api/v1/onboarding/{onboarding_id}',
            headers=self._headers('onboard_api_other_faculty', 'OtherFacultyPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_admin_sees_all_records(self):
        headers = self._faculty_headers()
        self.url_open('/api/v1/onboarding', headers=headers, json={}, method='POST')
        listing = self.url_open(
            '/api/v1/onboarding', headers=self._headers('onboard_api_admin', 'AdminPass1!')).json()['data']['onboarding']
        self.assertGreaterEqual(len(listing), 1)
