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

    def _post(self, path, headers=None):
        return self.url_open(path, headers=headers or self._staff_headers(), method='POST')

    def test_visit_detail_refer_cancel_reset(self):
        visit = self.env['op.health.visit'].create({
            'student_id': self.student.id, 'visit_type': 'injury', 'symptoms': 'Sprained ankle'})
        student_headers = self._headers('health_api_student', 'StudentPass1!')
        detail = self.url_open(f'/api/v1/health/visits/{visit.id}', headers=self._staff_headers())
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['data']['symptoms'], 'Sprained ankle')
        self.assertEqual(detail.json()['data']['patient_type'], 'student')
        self.assertEqual(self.url_open(f'/api/v1/health/visits/{visit.id}', headers=student_headers).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/health/visits/999999', headers=self._staff_headers()).status_code, 404)

        for action in ('refer', 'cancel', 'reset'):
            self.assertEqual(self._post(f'/api/v1/health/visits/{visit.id}/{action}', student_headers).status_code, 403)
        self.assertEqual(self._post(f'/api/v1/health/visits/{visit.id}/refer').json()['data']['state'], 'referred')
        self.assertEqual(self._post(f'/api/v1/health/visits/{visit.id}/cancel').json()['data']['state'], 'cancelled')
        self.assertEqual(self._post(f'/api/v1/health/visits/{visit.id}/reset').json()['data']['state'], 'draft')
        self.assertEqual(self._post('/api/v1/health/visits/999999/cancel').status_code, 404)

    def test_checkup_detail_cancel_reset(self):
        checkup = self.env['op.health.checkup'].create({
            'student_id': self.student.id, 'height_cm': 160.0, 'weight_kg': 64.0})
        detail = self.url_open(f'/api/v1/health/checkups/{checkup.id}', headers=self._staff_headers())
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertAlmostEqual(detail.json()['data']['bmi'], 25.0, places=1)
        self.assertEqual(self.url_open(f'/api/v1/health/checkups/{checkup.id}',
                                       headers=self._headers('health_api_student', 'StudentPass1!')).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/health/checkups/999999', headers=self._staff_headers()).status_code, 404)

        cancelled = self._post(f'/api/v1/health/checkups/{checkup.id}/cancel')
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()['data']['state'], 'cancelled')
        self.assertEqual(self._post(f'/api/v1/health/checkups/{checkup.id}/reset').json()['data']['state'], 'scheduled')
        self.assertEqual(self._post(f'/api/v1/health/checkups/{checkup.id}/reset',
                                    self._headers('health_api_student', 'StudentPass1!')).status_code, 403)

    def test_vaccination_detail_miss_cancel_reset(self):
        vaccine = self.env['op.health.vaccine.type'].create({'name': 'API Detail Vaccine'})
        vaccination = self.env['op.health.vaccination'].create({
            'student_id': self.student.id, 'vaccine_id': vaccine.id, 'dose_number': 2})
        detail = self.url_open(f'/api/v1/health/vaccinations/{vaccination.id}', headers=self._staff_headers())
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['data']['vaccine'], 'API Detail Vaccine')
        self.assertEqual(detail.json()['data']['dose_number'], 2)
        self.assertEqual(self.url_open(f'/api/v1/health/vaccinations/{vaccination.id}',
                                       headers=self._headers('health_api_student', 'StudentPass1!')).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/health/vaccinations/999999', headers=self._staff_headers()).status_code, 404)

        base = f'/api/v1/health/vaccinations/{vaccination.id}'
        self.assertEqual(self._post(f'{base}/miss', self._headers('health_api_student', 'StudentPass1!')).status_code, 403)
        self.assertEqual(self._post(f'{base}/miss').json()['data']['state'], 'missed')
        self.assertEqual(self._post(f'{base}/reset').json()['data']['state'], 'scheduled')
        self.assertEqual(self._post(f'{base}/cancel').json()['data']['state'], 'cancelled')
        self.assertEqual(self._post('/api/v1/health/vaccinations/999999/miss').status_code, 404)

    def test_lists(self):
        visit = self.env['op.health.visit'].create({'student_id': self.student.id, 'visit_type': 'illness'})
        checkup = self.env['op.health.checkup'].create({'student_id': self.student.id, 'height_cm': 140, 'weight_kg': 35})
        vaccine = self.env['op.health.vaccine.type'].create({'name': 'API List Vaccine'})
        vaccination = self.env['op.health.vaccination'].create({'student_id': self.student.id, 'vaccine_id': vaccine.id})
        for path, key, record in (('visits', 'visits', visit), ('checkups', 'checkups', checkup),
                                  ('vaccinations', 'vaccinations', vaccination)):
            resp = self.url_open(f'/api/v1/health/{path}', headers=self._staff_headers())
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertIn(record.id, [r['id'] for r in resp.json()['data'][key]], path)
            self.assertEqual(self.url_open(f'/api/v1/health/{path}', headers=self._headers(
                'health_api_student', 'StudentPass1!')).status_code, 403, path)
