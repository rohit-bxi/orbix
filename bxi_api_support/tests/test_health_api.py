# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportHealth(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.staff_user = mail_new_test_user(
            cls.env, login='health_api_staff', groups='base.group_user,op_health_center.group_health_staff',
            password='StaffPass1!')
        cls.student_user = mail_new_test_user(
            cls.env, login='health_api_student', groups='base.group_user', password='StudentPass1!')
        cls.student = cls._create_student('HEALTHAPI-001', user=cls.student_user)

    def _staff_headers(self):
        return self._headers('health_api_staff', 'StaffPass1!')

    def test_visits_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/health/visits').status_code, 401)

    def test_student_cannot_access_own_health_records(self):
        """Confirms the deliberate design choice: unlike fee/canteen/uniform
        domains, health records have no parent/student self-access at all in
        the underlying module, so this API does not invent one either."""
        student_headers = self._headers('health_api_student', 'StudentPass1!')
        resp = self.url_open('/api/v1/health/visits', headers=student_headers)
        self.assertEqual(resp.status_code, 403)

    def test_staff_full_visit_lifecycle(self):
        headers = self._staff_headers()
        create = self.url_open('/api/v1/health/visits', headers=headers, json={
            'student_id': self.student.id, 'visit_type': 'illness', 'symptoms': 'Fever',
        })
        self.assertEqual(create.status_code, 201)
        visit_id = create.json()['data']['id']

        confirm = self.url_open(f'/api/v1/health/visits/{visit_id}/confirm', headers=headers, method='POST')
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.json()['data']['state'], 'confirmed')

        treat = self.url_open(f'/api/v1/health/visits/{visit_id}/start-treatment', headers=headers, method='POST')
        self.assertEqual(treat.status_code, 200)

        resolve = self.url_open(f'/api/v1/health/visits/{visit_id}/resolve', headers=headers, method='POST')
        self.assertEqual(resolve.status_code, 200)
        self.assertEqual(resolve.json()['data']['state'], 'resolved')

    def test_checkup_and_vaccination_lifecycle(self):
        headers = self._staff_headers()
        checkup = self.url_open('/api/v1/health/checkups', headers=headers, json={
            'student_id': self.student.id, 'height_cm': 150.0, 'weight_kg': 45.0,
        }).json()['data']
        self.assertAlmostEqual(checkup['bmi'], 20.0, places=1)

        complete_checkup = self.url_open(
            f'/api/v1/health/checkups/{checkup["id"]}/complete', headers=headers, method='POST')
        self.assertEqual(complete_checkup.status_code, 200)
        self.assertEqual(complete_checkup.json()['data']['state'], 'completed')

        vaccine = self.env['op.health.vaccine.type'].create({'name': 'API Test Vaccine'})
        vaccination = self.url_open('/api/v1/health/vaccinations', headers=headers, json={
            'student_id': self.student.id, 'vaccine_id': vaccine.id,
        }).json()['data']

        complete_vacc = self.url_open(
            f'/api/v1/health/vaccinations/{vaccination["id"]}/complete', headers=headers, method='POST')
        self.assertEqual(complete_vacc.status_code, 200)
        self.assertEqual(complete_vacc.json()['data']['state'], 'completed')
        self.assertTrue(complete_vacc.json()['data']['date_administered'])

    def test_create_visit_missing_patient_rejected(self):
        resp = self.url_open('/api/v1/health/visits', headers=self._staff_headers(), json={'visit_type': 'illness'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_patient')
