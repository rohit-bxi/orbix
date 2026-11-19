# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportPeopleAadhaar(ApiSupportHttpCase):
    """"aadhaar_number" on the teacher/student/parent create & update APIs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course, cls.batch = cls._create_class('UMAA')
        mail_new_test_user(cls.env, login='umaa_office', password='OfficePass1!',
                           groups='base.group_user,openeducat_core.group_op_back_office_admin')
        cls.relationship = cls.env['op.parent.relationship'].search([], limit=1) or \
            cls.env['op.parent.relationship'].create({'name': 'Guardian'})

    def _post(self, url, body):
        return self.url_open(url, headers=self._headers('umaa_office', 'OfficePass1!'), json=body, method='POST')

    def _student(self, roll, **extra):
        body = {'first_name': 'Aad', 'last_name': 'Har%s' % roll, 'gender': 'm', 'email': 'aad%s@umaa.test' % roll,
                'enrollment': {'course_id': self.course.id, 'batch_id': self.batch.id, 'roll_number': roll},
                'account': {'username': 'aad%s.umaa' % roll, 'password': 'AadPass%s99' % roll}}
        body.update(self._student_screen_fields())
        body.update(extra)
        return self._post('/api/v1/students', body)

    def test_create_with_aadhaar_masked_and_verified(self):
        resp = self._student('1', aadhaar_number='2345 6789 0124')
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertEqual(data['aadhaar']['number_masked'], 'XXXX XXXX 0124')
        self.assertEqual(data['aadhaar']['last4'], '0124')
        self.assertEqual(data['aadhaar']['status'], 'verified')
        self.assertNotIn('234567890124', resp.text, 'The full number is never returned.')
        self.assertEqual(self.env['op.student'].browse(data['id']).aadhar_card, '234567890124')

    def test_teacher_and_parent_update(self):
        teacher = self._post('/api/v1/teachers', {
            'first_name': 'Aad', 'last_name': 'Teacher', 'gender': 'female', 'birth_date': '1987-07-07'})
        self.assertEqual(teacher.status_code, 201, teacher.text)
        teacher_id = teacher.json()['data']['id']
        resp = self._post('/api/v1/teachers/%s/update' % teacher_id, {'aadhaar_number': '345678901238'})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['aadhaar']['last4'], '1238')
        resp = self._post('/api/v1/teachers/%s/update' % teacher_id, {'aadhaar_number': None})
        self.assertEqual(resp.json()['data']['aadhaar'],
                         {'number_masked': None, 'last4': None, 'status': 'unverified', 'verified_at': None})

        student_id = self._student('2').json()['data']['id']
        parent = self._post('/api/v1/parents', {
            'name': 'Aad Parent', 'mobile': '9800099911', 'relationship_id': self.relationship.id,
            'student_ids': [student_id], 'aadhaar_number': '456789012341',
            'account': {'username': 'aad.parent', 'password': 'AadParent99'}})
        self.assertEqual(parent.status_code, 201, parent.text)
        self.assertEqual(parent.json()['data']['aadhaar']['status'], 'verified')

    def test_invalid_and_taken_numbers(self):
        resp = self._student('3', aadhaar_number='234567890125')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_aadhaar')
        self.assertFalse(self.env['op.student'].search([('email', '=', 'aad3@umaa.test')]))

        self.assertEqual(self._student('4', aadhaar_number='567890123458').status_code, 201)
        resp = self._student('5', aadhaar_number='5678 9012 3458')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error']['code'], 'aadhaar_in_use')
        self.assertFalse(self.env['op.student'].search([('email', '=', 'aad5@umaa.test')]),
                         'Nothing of the request is saved.')
