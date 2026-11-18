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

    def _add(self, teacher, day='monday', course=None, batch=None):
        return self.url_open('/api/v1/timetable/admin/add-period', headers=self._headers_coord(), json={
            'teacher_id': teacher.id, 'course_id': (course or self.course).id, 'batch_id': (batch or self.batch).id,
            'day': day, 'timing_id': self.timing.id, 'subject_id': self.subject.id,
        })

    def _timetable(self, course=None, batch=None):
        return self.env['bxi.timetable'].search([
            ('course_id', '=', (course or self.course).id), ('batch_id', '=', (batch or self.batch).id)])

    def test_get_timetable_detail(self):
        self.assertEqual(self._add(self.faculty).status_code, 200)
        timetable = self._timetable()
        resp = self.url_open(f'/api/v1/timetable/admin/timetables/{timetable.id}', headers=self._headers_coord())
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertEqual(data['id'], timetable.id)
        self.assertEqual([(line['day'], line['teacher']) for line in data['lines']],
                         [('monday', self.faculty.display_name)])
        self.assertEqual(self.url_open(f'/api/v1/timetable/admin/timetables/{timetable.id}',
                                       headers=self._headers('tt_api_other', 'OtherPass1!')).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/timetable/admin/timetables/999999',
                                       headers=self._headers_coord()).status_code, 404)

    def test_remove_period(self):
        self._add(self.faculty)
        line = self._timetable().line_ids
        self.assertEqual(self.url_open('/api/v1/timetable/admin/remove-period', json={'line_id': line.id},
                                       headers=self._headers('tt_api_other', 'OtherPass1!')).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/timetable/admin/remove-period', json={},
                                       headers=self._headers_coord(), method='POST').json()['error']['code'], 'missing_fields')
        # A locked timetable keeps its periods.
        self._timetable().action_lock()
        locked = self.url_open('/api/v1/timetable/admin/remove-period', json={'line_id': line.id},
                               headers=self._headers_coord())
        self.assertEqual(locked.status_code, 400)
        self.assertTrue(line.exists())
        self._timetable().action_unlock()
        resp = self.url_open('/api/v1/timetable/admin/remove-period', json={'line_id': line.id},
                             headers=self._headers_coord())
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(line.exists())

    def test_transfer_period(self):
        self._add(self.faculty)
        line = self._timetable().line_ids
        payload = {
            'from_teacher_id': self.faculty.id, 'course_id': self.course.id, 'batch_id': self.batch.id,
            'day': 'monday', 'timing_id': self.timing.id, 'to_teacher_id': self.other_faculty.id,
        }
        self.assertEqual(self.url_open('/api/v1/timetable/admin/transfer-period', json=payload,
                                       headers=self._headers('tt_api_other', 'OtherPass1!')).status_code, 403)
        # No period on Tuesday to transfer.
        none = self.url_open('/api/v1/timetable/admin/transfer-period', json=dict(payload, day='tuesday'),
                             headers=self._headers_coord())
        self.assertEqual(none.status_code, 400)
        # The receiving teacher is full unless the coordinator overrides the workload limit.
        self.other_faculty.max_weekly_periods = 0
        full = self.url_open('/api/v1/timetable/admin/transfer-period', json=payload, headers=self._headers_coord())
        self.assertEqual(full.status_code, 400)
        self.assertEqual(line.teacher_id, self.faculty)
        forced = self.url_open('/api/v1/timetable/admin/transfer-period',
                               json=dict(payload, force_workload_override=True), headers=self._headers_coord())
        self.assertEqual(forced.status_code, 200, forced.text)
        self.assertEqual(line.teacher_id, self.other_faculty)

    def test_reassign_class(self):
        new_course = self.env['op.course'].create({'name': 'TT API Course 2', 'code': 'TT-C2'})
        new_batch = self.env['op.batch'].create({
            'name': 'TT API Batch 2', 'code': 'TT-B2', 'course_id': new_course.id,
            'start_date': '2026-06-01', 'end_date': '2027-03-31',
        })
        payload = {
            'teacher_id': self.faculty.id, 'current_course_id': self.course.id, 'current_batch_id': self.batch.id,
            'new_course_id': new_course.id, 'new_batch_id': new_batch.id,
        }
        # Nothing to move yet.
        self.assertEqual(self.url_open('/api/v1/timetable/admin/reassign-class', json=payload,
                                       headers=self._headers_coord()).status_code, 400)
        self._add(self.faculty)
        # The destination already has a period in the same slot.
        self._add(self.other_faculty, course=new_course, batch=new_batch)
        clash = self.url_open('/api/v1/timetable/admin/reassign-class', json=payload, headers=self._headers_coord())
        self.assertEqual(clash.status_code, 400)
        self.assertEqual(len(self._timetable().line_ids), 1)

        self._timetable(new_course, new_batch).line_ids.unlink()
        self.assertEqual(self.url_open('/api/v1/timetable/admin/reassign-class', json=payload,
                                       headers=self._headers('tt_api_other', 'OtherPass1!')).status_code, 403)
        moved = self.url_open('/api/v1/timetable/admin/reassign-class', json=payload, headers=self._headers_coord())
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertFalse(self._timetable().line_ids)
        self.assertEqual(self._timetable(new_course, new_batch).line_ids.teacher_id, self.faculty)
