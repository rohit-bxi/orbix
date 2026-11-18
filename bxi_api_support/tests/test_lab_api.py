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

    def test_session_start_done_cancel_reset(self):
        session_id = self._create_session().json()['data']['id']
        headers = self._instructor_headers()
        other = self._headers('lab_api_other_instructor', 'OtherInstructorPass1!')
        for action in ('start', 'done', 'cancel', 'reset'):
            self.assertEqual(self.url_open(f'/api/v1/lab/sessions/{session_id}/{action}', headers=other,
                                           method='POST').status_code, 403, action)
        self.url_open(f'/api/v1/lab/sessions/{session_id}/confirm', headers=headers, method='POST')
        started = self.url_open(f'/api/v1/lab/sessions/{session_id}/start', headers=headers, method='POST')
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(started.json()['data']['state'], 'in_progress')
        done = self.url_open(f'/api/v1/lab/sessions/{session_id}/done', headers=headers, method='POST')
        self.assertEqual(done.json()['data']['state'], 'done')
        # The lab admin can manage any instructor's session.
        admin = self._headers('lab_api_admin', 'AdminPass1!')
        reset = self.url_open(f'/api/v1/lab/sessions/{session_id}/reset', headers=admin, method='POST')
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(reset.json()['data']['state'], 'draft')
        cancelled = self.url_open(f'/api/v1/lab/sessions/{session_id}/cancel', headers=headers, method='POST')
        self.assertEqual(cancelled.json()['data']['state'], 'cancelled')
        self.assertEqual(self.url_open('/api/v1/lab/sessions/999999/start', headers=admin, method='POST').status_code, 404)

    def test_equipment_issue_detail_and_mark_damaged(self):
        session_id = self._create_session().json()['data']['id']
        headers = self._instructor_headers()
        issue_id = self.url_open('/api/v1/lab/equipment-issues', headers=headers, json={
            'session_id': session_id, 'equipment_id': self.equipment.id, 'issued_qty': 1,
        }).json()['data']['id']
        detail = self.url_open(f'/api/v1/lab/equipment-issues/{issue_id}', headers=headers)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual((detail.json()['data']['equipment'], detail.json()['data']['issued_qty']), ('API Microscope', 1))
        self.assertEqual(detail.json()['data']['session_id'], session_id)
        other = self._headers('lab_api_other_instructor', 'OtherInstructorPass1!')
        self.assertEqual(self.url_open(f'/api/v1/lab/equipment-issues/{issue_id}', headers=other).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/lab/equipment-issues/999999', headers=headers).status_code, 404)

        url = f'/api/v1/lab/equipment-issues/{issue_id}/mark-damaged'
        self.assertEqual(self.url_open(url, headers=other, method='POST').status_code, 403)
        damaged = self.url_open(url, headers=headers, method='POST')
        self.assertEqual(damaged.status_code, 200, damaged.text)
        self.assertEqual(damaged.json()['data']['state'], 'damaged')

    def test_session_detail_and_issue_list(self):
        session_id = self._create_session().json()['data']['id']
        headers = self._instructor_headers()
        detail = self.url_open(f'/api/v1/lab/sessions/{session_id}', headers=headers)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual((detail.json()['data']['room'], detail.json()['data']['state']), ('API Lab Room', 'draft'))
        issue_id = self.url_open('/api/v1/lab/equipment-issues', headers=headers, json={
            'session_id': session_id, 'equipment_id': self.equipment.id, 'issued_qty': 1}).json()['data']['id']
        own = self.url_open(f'/api/v1/lab/equipment-issues?session_id={session_id}', headers=headers)
        self.assertEqual(own.status_code, 200, own.text)
        self.assertEqual([i['id'] for i in own.json()['data']['issues']], [issue_id])
        other = self.url_open('/api/v1/lab/equipment-issues', headers=self._headers(
            'lab_api_other_instructor', 'OtherInstructorPass1!'))
        self.assertEqual(other.json()['data']['issues'], [])
