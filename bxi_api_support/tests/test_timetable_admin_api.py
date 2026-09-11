# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportTimetableAdmin(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coordinator_user = mail_new_test_user(
            cls.env, login='tt_api_coordinator',
            groups='base.group_user,bxi_class_timetable_inhencement.group_class_timetable_coordinator',
            password='CoordPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='tt_api_other', groups='base.group_user', password='OtherPass1!')
        cls.course = cls.env['op.course'].create({'name': 'TT API Course', 'code': 'TT-C1'})
        cls.batch = cls.env['op.batch'].create({
            'name': 'TT API Batch', 'code': 'TT-B1', 'course_id': cls.course.id,
            'start_date': '2026-06-01', 'end_date': '2027-03-31',
        })
        cls.subject = cls.env['op.subject'].create({'name': 'TT API Subject', 'code': 'TT-S1'})
        cls.timing = cls.env['op.timing'].create({'name': 'Period 1', 'hour': '9', 'minute': '00', 'am_pm': 'am'})
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'TT', 'last_name': 'Teacher', 'gender': 'male', 'birth_date': '1985-01-01',
        })
        cls.other_faculty = cls.env['op.faculty'].create({
            'first_name': 'TT', 'last_name': 'Other', 'gender': 'female', 'birth_date': '1985-01-01',
        })

    def _headers_coord(self):
        return self._headers('tt_api_coordinator', 'CoordPass1!')

    def test_timetables_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/timetable/admin/timetables').status_code, 401)

    def test_non_coordinator_cannot_add_period(self):
        resp = self.url_open('/api/v1/timetable/admin/add-period', headers=self._headers('tt_api_other', 'OtherPass1!'), json={
            'teacher_id': self.faculty.id, 'course_id': self.course.id, 'batch_id': self.batch.id,
            'day': 'monday', 'timing_id': self.timing.id, 'subject_id': self.subject.id,
        })
        self.assertEqual(resp.status_code, 403)

    def test_add_period_then_lock_blocks_further_changes(self):
        headers = self._headers_coord()
        add_resp = self.url_open('/api/v1/timetable/admin/add-period', headers=headers, json={
            'teacher_id': self.faculty.id, 'course_id': self.course.id, 'batch_id': self.batch.id,
            'day': 'monday', 'timing_id': self.timing.id, 'subject_id': self.subject.id,
        })
        self.assertEqual(add_resp.status_code, 200)

        timetables = self.url_open(
            f'/api/v1/timetable/admin/timetables?course_id={self.course.id}&batch_id={self.batch.id}',
            headers=headers).json()['data']['timetables']
        self.assertEqual(len(timetables), 1)
        self.assertEqual(len(timetables[0]['lines']), 1)
        timetable_id = timetables[0]['id']

        lock_resp = self.url_open(
            f'/api/v1/timetable/admin/timetables/{timetable_id}/lock', headers=headers, method='POST')
        self.assertEqual(lock_resp.status_code, 200)
        self.assertTrue(lock_resp.json()['data']['locked'])

        blocked = self.url_open('/api/v1/timetable/admin/add-period', headers=headers, json={
            'teacher_id': self.other_faculty.id, 'course_id': self.course.id, 'batch_id': self.batch.id,
            'day': 'tuesday', 'timing_id': self.timing.id, 'subject_id': self.subject.id,
        })
        self.assertEqual(blocked.status_code, 400)

        unlock_resp = self.url_open(
            f'/api/v1/timetable/admin/timetables/{timetable_id}/unlock', headers=headers, method='POST')
        self.assertEqual(unlock_resp.status_code, 200)
        self.assertFalse(unlock_resp.json()['data']['locked'])

    def test_add_period_missing_fields_rejected(self):
        resp = self.url_open('/api/v1/timetable/admin/add-period', headers=self._headers_coord(), json={
            'teacher_id': self.faculty.id,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_fields')

    def test_faculty_workload_endpoint(self):
        resp = self.url_open('/api/v1/timetable/admin/faculty-workload', headers=self._headers_coord())
        self.assertEqual(resp.status_code, 200)
        names = [f['name'] for f in resp.json()['data']['faculty']]
        self.assertIn(self.faculty.name, names)
