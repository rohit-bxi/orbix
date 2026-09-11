# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import date, timedelta

from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportAttendance(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.teacher_user = mail_new_test_user(
            cls.env, login='attendance_api_teacher',
            groups='base.group_user,openeducat_core.group_op_faculty',
            password='TeacherPass1!')
        cls.other_teacher_user = mail_new_test_user(
            cls.env, login='attendance_api_other_teacher',
            groups='base.group_user,openeducat_core.group_op_faculty',
            password='OtherTeacherPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='attendance_api_other', groups='base.group_user', password='OtherPass1!')
        cls.student = cls._create_student('ATTAPI-001')

        cls.course = cls.env['op.course'].create({'name': 'API Attendance Course', 'code': 'ATT-C1'})
        cls.batch = cls.env['op.batch'].create({
            'name': 'API Attendance Batch', 'code': 'ATT-B1', 'course_id': cls.course.id,
            'start_date': date.today(), 'end_date': date.today() + timedelta(days=300),
        })
        cls.subject = cls.env['op.subject'].create({'name': 'API Attendance Subject', 'code': 'ATT-S1'})
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'API', 'last_name': 'Teacher', 'gender': 'male',
            'birth_date': date(1985, 1, 1), 'user_id': cls.teacher_user.id,
        })
        cls.session = cls.env['op.session'].create({
            'course_id': cls.course.id, 'batch_id': cls.batch.id, 'subject_id': cls.subject.id,
            'faculty_id': cls.faculty.id, 'start_datetime': '2026-01-01 09:00:00',
            'end_datetime': '2026-01-01 10:00:00', 'student_ids': [(6, 0, [cls.student.id])],
        })

    def test_checkin_requires_auth(self):
        resp = self.url_open('/api/v1/attendance/checkin', method='POST', json={'student_id': self.student.id})
        self.assertEqual(resp.status_code, 401)

    def test_non_teacher_cannot_checkin(self):
        resp = self.url_open(
            '/api/v1/attendance/checkin', headers=self._headers('attendance_api_other', 'OtherPass1!'),
            json={'student_id': self.student.id})
        self.assertEqual(resp.status_code, 403)

    def test_teacher_can_checkin_student(self):
        resp = self.url_open(
            '/api/v1/attendance/checkin', headers=self._headers('attendance_api_teacher', 'TeacherPass1!'),
            json={'student_id': self.student.id})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['data']['student_id'], self.student.id)

    def test_checkin_unknown_student_not_found(self):
        resp = self.url_open(
            '/api/v1/attendance/checkin', headers=self._headers('attendance_api_teacher', 'TeacherPass1!'),
            json={'student_id': 999999})
        self.assertEqual(resp.status_code, 404)

    def test_mark_and_roster_reflects_status(self):
        headers = self._headers('attendance_api_teacher', 'TeacherPass1!')
        mark = self.url_open('/api/v1/attendance/mark', headers=headers, json={
            'student_id': self.student.id, 'session_id': self.session.id, 'status': 'absent',
            'remark': 'Called in sick.',
        })
        self.assertEqual(mark.status_code, 200)
        self.assertEqual(mark.json()['data']['status'], 'absent')

        roster = self.url_open(f'/api/v1/attendance/sessions/{self.session.id}/roster', headers=headers)
        self.assertEqual(roster.status_code, 200)
        entries = roster.json()['data']['roster']
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['status'], 'absent')

    def test_mark_invalid_status_rejected(self):
        headers = self._headers('attendance_api_teacher', 'TeacherPass1!')
        resp = self.url_open('/api/v1/attendance/mark', headers=headers, json={
            'student_id': self.student.id, 'session_id': self.session.id, 'status': 'bogus',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_status')

    def test_other_teacher_cannot_mark_session_they_do_not_own(self):
        resp = self.url_open(
            '/api/v1/attendance/mark', headers=self._headers('attendance_api_other_teacher', 'OtherTeacherPass1!'),
            json={'student_id': self.student.id, 'session_id': self.session.id, 'status': 'present'})
        self.assertEqual(resp.status_code, 403)

    def test_roster_session_not_found(self):
        resp = self.url_open(
            '/api/v1/attendance/sessions/999999/roster', headers=self._headers('attendance_api_teacher', 'TeacherPass1!'))
        self.assertEqual(resp.status_code, 404)

    def test_checkout_after_checkin(self):
        headers = self._headers('attendance_api_teacher', 'TeacherPass1!')
        checkin = self.url_open(
            '/api/v1/attendance/checkin', headers=headers,
            json={'student_id': self.student.id, 'check_in': '2026-02-01 09:00:00'})
        attendance_id = checkin.json()['data']['id']

        checkout = self.url_open(
            f'/api/v1/attendance/checkout/{attendance_id}', headers=headers,
            json={'check_out': '2026-02-01 10:00:00'})
        self.assertEqual(checkout.status_code, 200)
        self.assertTrue(checkout.json()['data']['check_out'])

        second_checkout = self.url_open(f'/api/v1/attendance/checkout/{attendance_id}', headers=headers, json={}, method='POST')
        self.assertEqual(second_checkout.status_code, 400)
        self.assertEqual(second_checkout.json()['error']['code'], 'already_checked_out')
