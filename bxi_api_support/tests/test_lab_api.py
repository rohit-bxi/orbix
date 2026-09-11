# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportLab(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.instructor_user = mail_new_test_user(
            cls.env, login='lab_api_instructor',
            groups='base.group_user,op_student_lab_management.group_lab_instructor',
            password='InstructorPass1!')
        cls.other_instructor_user = mail_new_test_user(
            cls.env, login='lab_api_other_instructor',
            groups='base.group_user,op_student_lab_management.group_lab_instructor',
            password='OtherInstructorPass1!')
        cls.admin_user = mail_new_test_user(
            cls.env, login='lab_api_admin', groups='base.group_user,op_student_lab_management.group_lab_admin',
            password='AdminPass1!')
        cls.instructor_faculty = cls.env['op.faculty'].create({
            'first_name': 'Lab', 'last_name': 'Instructor', 'gender': 'male', 'birth_date': '1985-01-01',
            'user_id': cls.instructor_user.id,
        })
        cls.room = cls.env['lab.room'].create({'name': 'API Lab Room', 'code': 'LAB-R1'})
        cls.course = cls.env['op.course'].create({'name': 'Lab API Course', 'code': 'LAB-C1'})
        cls.batch = cls.env['op.batch'].create({
            'name': 'Lab API Batch', 'code': 'LAB-B1', 'course_id': cls.course.id,
            'start_date': '2026-06-01', 'end_date': '2027-03-31',
        })
        cls.equipment = cls.env['lab.equipment'].create({
            'name': 'API Microscope', 'lab_id': cls.room.id, 'quantity_total': 5,
        })

    def _instructor_headers(self):
        return self._headers('lab_api_instructor', 'InstructorPass1!')

    def _create_session(self):
        return self.url_open('/api/v1/lab/sessions', headers=self._instructor_headers(), json={
            'room_id': self.room.id, 'course_id': self.course.id, 'batch_id': self.batch.id,
            'start_time': 9.0, 'end_time': 10.0,
        })

    def test_sessions_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/lab/sessions').status_code, 401)

    def test_instructor_can_create_and_confirm_session(self):
        create = self._create_session()
        self.assertEqual(create.status_code, 201)
        session = create.json()['data']
        self.assertEqual(session['faculty'], self.instructor_faculty.display_name)

        confirm = self.url_open(
            f'/api/v1/lab/sessions/{session["id"]}/confirm', headers=self._instructor_headers(), method='POST')
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.json()['data']['state'], 'confirmed')

    def test_other_instructor_cannot_view_session(self):
        session = self._create_session().json()['data']
        resp = self.url_open(
            f'/api/v1/lab/sessions/{session["id"]}',
            headers=self._headers('lab_api_other_instructor', 'OtherInstructorPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_admin_sees_all_sessions(self):
        self._create_session()
        resp = self.url_open('/api/v1/lab/sessions', headers=self._headers('lab_api_admin', 'AdminPass1!'))
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()['meta']['total'], 1)

    def test_equipment_issue_and_return_flow(self):
        session = self._create_session().json()['data']
        headers = self._instructor_headers()
        issue = self.url_open('/api/v1/lab/equipment-issues', headers=headers, json={
            'session_id': session['id'], 'equipment_id': self.equipment.id, 'issued_qty': 2,
        })
        self.assertEqual(issue.status_code, 201)
        issue_id = issue.json()['data']['id']
        self.assertEqual(issue.json()['data']['state'], 'issued')

        return_resp = self.url_open(
            f'/api/v1/lab/equipment-issues/{issue_id}/return', headers=headers, json={'returned_qty': 2})
        self.assertEqual(return_resp.status_code, 200)
        self.assertEqual(return_resp.json()['data']['state'], 'returned')

    def test_over_allocation_rejected(self):
        session = self._create_session().json()['data']
        resp = self.url_open('/api/v1/lab/equipment-issues', headers=self._instructor_headers(), json={
            'session_id': session['id'], 'equipment_id': self.equipment.id, 'issued_qty': 999,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'validation_error')
