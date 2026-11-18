# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportAcademicAdmin(ApiSupportHttpCase):
    """PTM scheduling, school holidays and archiving notices."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coord_user = mail_new_test_user(
            cls.env, login='acad_coord', password='CoordPass1!',
            groups='base.group_user,bxi_academic_management.group_academic_coordinator')
        cls.teacher_user = mail_new_test_user(
            cls.env, login='acad_teacher', password='TeacherPass1!',
            groups='base.group_user,openeducat_core.group_op_faculty')
        cls.parent_user = mail_new_test_user(
            cls.env, login='acad_parent', password='ParentPass1!', groups='base.group_portal')
        cls.notice_user = mail_new_test_user(
            cls.env, login='acad_notice', password='NoticePass1!',
            groups='base.group_user,bxi_school_notice.group_notice_manager')
        cls.course, cls.batch = cls._create_class('ACAD')
        cls.student = cls._create_student('ACAD-001')
        cls._enroll(cls.student, cls.course, cls.batch)
        cls.parent = cls._create_parent(cls.parent_user, cls.student)
        cls.env.company.resource_calendar_id.tz = 'Asia/Kolkata'

    def _coord(self):
        return self._headers('acad_coord', 'CoordPass1!')

    def _post(self, path, payload=None, headers=None):
        return self.url_open(path, headers=headers or self._coord(), json=payload or {}, method='POST')

    def _ptm(self, **extra):
        return self._post('/api/v1/academic/ptm-meetings', dict({
            'name': 'Acad PTM', 'start_datetime': '2026-12-12 04:30:00', 'end_datetime': '2026-12-12 07:30:00',
            'venue': 'Main Hall', 'class_ids': [self.course.id]}, **extra))

    def test_access(self):
        for headers in (self._headers('acad_teacher', 'TeacherPass1!'), self._headers('acad_parent', 'ParentPass1!')):
            self.assertEqual(self._post('/api/v1/academic/ptm-meetings', {}, headers).status_code, 403)
            self.assertEqual(self._post('/api/v1/calendar/holidays', {}, headers).status_code, 403)

    def test_ptm_lifecycle(self):
        created = self._ptm()
        self.assertEqual(created.status_code, 201, created.text)
        meeting = created.json()['data']
        self.assertEqual(meeting['parents_notified'], 1)
        # The parent sees it in their list.
        mine = self.url_open('/api/v1/academic/ptm-meetings/my?include_past=1',
                             headers=self._headers('acad_parent', 'ParentPass1!')).json()['data']['meetings']
        self.assertIn(meeting['id'], [m['id'] for m in mine])
        moved = self._post(f"/api/v1/academic/ptm-meetings/{meeting['id']}/update", {'venue': 'Library'})
        self.assertEqual(moved.json()['data']['venue'], 'Library')
        bad = self._post(f"/api/v1/academic/ptm-meetings/{meeting['id']}/update",
                         {'end_datetime': '2026-12-12 03:00:00'})
        self.assertEqual(bad.status_code, 400)
        archived = self._post(f"/api/v1/academic/ptm-meetings/{meeting['id']}/archive")
        self.assertFalse(archived.json()['data']['active'])
        mine = self.url_open('/api/v1/academic/ptm-meetings/my?include_past=1',
                             headers=self._headers('acad_parent', 'ParentPass1!')).json()['data']['meetings']
        self.assertNotIn(meeting['id'], [m['id'] for m in mine])
        self.assertTrue(self._post(f"/api/v1/academic/ptm-meetings/{meeting['id']}/restore").json()['data']['active'])
        self.assertEqual(self._ptm(class_ids=[]).json()['error']['code'], 'missing_class_ids')

    def test_holidays(self):
        created = self._post('/api/v1/calendar/holidays', {
            'name': 'Acad Winter Break', 'date_from': '2026-12-24', 'date_to': '2026-12-26'})
        self.assertEqual(created.status_code, 201, created.text)
        holiday = created.json()['data']
        # Whole days in the school's time zone (IST, UTC+5:30).
        self.assertEqual(holiday['date_from'], '2026-12-23 18:30:00')
        self.assertEqual(holiday['first_day'], '2026-12-24')
        self.assertEqual(holiday['last_day'], '2026-12-26')
        listed = self.url_open('/api/v1/calendar/holidays?date_from=2026-12-01&date_to=2026-12-31',
                               headers=self._headers('acad_parent', 'ParentPass1!')).json()['data']['holidays']
        self.assertIn(holiday['id'], [h['id'] for h in listed])
        updated = self._post(f"/api/v1/calendar/holidays/{holiday['id']}/update", {'date_to': '2026-12-31'})
        self.assertEqual(updated.json()['data']['last_day'], '2026-12-31')
        self.assertEqual(self._post(f"/api/v1/calendar/holidays/{holiday['id']}/update", {'date_to': '2026-12-01'})
                         .json()['error']['code'], 'invalid_dates')
        self.assertEqual(self._post('/api/v1/calendar/holidays', {'name': 'X', 'date_from': '2026-13-01',
                                                                  'date_to': '2026-12-02'}).status_code, 400)
        deleted = self._post(f"/api/v1/calendar/holidays/{holiday['id']}/delete")
        self.assertTrue(deleted.json()['data']['deleted'])
        self.assertEqual(self._post(f"/api/v1/calendar/holidays/{holiday['id']}/delete").status_code, 404)

    def test_archive_notice(self):
        notice_headers = self._headers('acad_notice', 'NoticePass1!')
        notice = self._post('/api/v1/notices', {'title': 'Acad Notice', 'body': 'Hello',
                                                'target_audience': 'all_parents'}, notice_headers).json()['data']
        parent = self._headers('acad_parent', 'ParentPass1!')
        self.assertEqual(self.url_open(f"/api/v1/notices/{notice['id']}", headers=parent).status_code, 200)
        self.assertEqual(self._post(f"/api/v1/notices/{notice['id']}/archive", {}, parent).status_code, 403)
        archived = self._post(f"/api/v1/notices/{notice['id']}/archive", {}, notice_headers)
        self.assertFalse(archived.json()['data']['active'])
        self.assertEqual(self.url_open(f"/api/v1/notices/{notice['id']}", headers=parent).status_code, 403)
        self.assertNotIn(notice['id'], [n['id'] for n in self.url_open('/api/v1/notices', headers=parent)
                                        .json()['data']['notices']])
        restored = self._post(f"/api/v1/notices/{notice['id']}/restore", {}, notice_headers)
        self.assertTrue(restored.json()['data']['active'])
