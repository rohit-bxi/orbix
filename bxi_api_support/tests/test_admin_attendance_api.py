# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase

URL = '/api/v1/admin/attendance'
RANGE = 'date_from=2026-03-02&date_to=2026-03-04'


@tagged('post_install', '-at_install')
class TestBxiApiSupportAdminAttendance(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coordinator_user = mail_new_test_user(
            cls.env, login='aatt_coord', password='CoordPass1!', tz='Asia/Kolkata',
            groups='base.group_user,bxi_academic_management.group_academic_coordinator')
        cls.office_user = mail_new_test_user(
            cls.env, login='aatt_office', password='OfficePass1!', tz='Asia/Kolkata',
            groups='base.group_user,openeducat_core.group_op_back_office_admin')
        cls.teacher_user = mail_new_test_user(
            cls.env, login='aatt_teacher', password='TeacherPass1!',
            groups='base.group_user,openeducat_core.group_op_faculty')
        cls.parent_user = mail_new_test_user(
            cls.env, login='aatt_parent', password='ParentPass1!', groups='base.group_portal')
        cls.faculty = cls._create_faculty(cls.teacher_user, first_name='Aatt')

        cls.course, cls.batch = cls._create_class('AATT')
        cls.other_course, cls.other_batch = cls._create_class('AATTO')
        cls.subject = cls.env['op.subject'].create({'name': 'Aatt Maths', 'code': 'AATT-M'})
        cls.other_subject = cls.env['op.subject'].create({'name': 'Aatt Science', 'code': 'AATT-S'})

        cls.alice = cls._create_student('AATT-001', first_name='Alice', last_name='Aatt')
        cls.bob = cls._create_student('AATT-002', first_name='Bob', last_name='Aatt')
        cls.cara = cls._create_student('AATT-003', first_name='Cara', last_name='Aatt')  # never marked
        cls.dan = cls._create_student('AATT-004', first_name='Dan', last_name='Aatt')
        for student in (cls.alice, cls.bob, cls.cara):
            cls._enroll(student, cls.course, cls.batch)
        cls._enroll(cls.dan, cls.other_course, cls.other_batch)
        cls.env['op.student.course'].search([('student_id', '=', cls.alice.id)]).roll_number = '1'

        def session(course, batch, subject, start):
            hour = int(start[11:13])
            return cls.env['op.session'].create({
                'course_id': course.id, 'batch_id': batch.id, 'subject_id': subject.id,
                'faculty_id': cls.faculty.id, 'start_datetime': start,
                'end_datetime': '%s %02d:00:00' % (start[:10], hour + 1),
            })

        cls.s_before = session(cls.course, cls.batch, cls.subject, '2026-02-27 04:00:00')
        cls.s_mon_1 = session(cls.course, cls.batch, cls.subject, '2026-03-02 04:00:00')
        cls.s_mon_2 = session(cls.course, cls.batch, cls.other_subject, '2026-03-02 05:00:00')
        cls.s_tue = session(cls.course, cls.batch, cls.subject, '2026-03-03 04:00:00')
        cls.s_other = session(cls.other_course, cls.other_batch, cls.subject, '2026-03-03 04:00:00')

        Attendance = cls.env['hr.attendance']

        def mark(student, sess, status):
            return Attendance.create({'employee_id': student.employee_id.id, 'session_id': sess.id, 'status': status})

        mark(cls.alice, cls.s_before, 'absent')        # outside the range
        mark(cls.alice, cls.s_mon_1, 'present')
        mark(cls.alice, cls.s_mon_2, 'absent')
        mark(cls.alice, cls.s_tue, 'present')
        mark(cls.bob, cls.s_mon_1, 'late')
        mark(cls.bob, cls.s_tue, 'absent')
        mark(cls.dan, cls.s_other, 'present')
        # A kiosk scan with no period: 2026-03-03 19:00 UTC is 00:30 on
        # 2026-03-04 in Asia/Kolkata, so it belongs to the 4th.
        cls.late_scan = Attendance.create({
            'employee_id': cls.alice.employee_id.id, 'status': 'present',
            'check_in': '2026-03-03 19:00:00', 'check_out': '2026-03-03 19:05:00',
        })

    def _get(self, query='', login='aatt_coord', password='CoordPass1!'):
        return self.url_open(f'{URL}?{query}', headers=self._headers(login, password))

    def _rows(self, resp):
        self.assertEqual(resp.status_code, 200, resp.text)
        return {row['student']['id']: row for row in resp.json()['data']['students']}

    # -- access ----------------------------------------------------------------

    def test_requires_auth(self):
        self.assertEqual(self.url_open(URL).status_code, 401)

    def test_teacher_and_parent_forbidden(self):
        self.assertEqual(self._get(login='aatt_teacher', password='TeacherPass1!').status_code, 403)
        self.assertEqual(self._get(login='aatt_parent', password='ParentPass1!').status_code, 403)

    def test_back_office_admin_allowed(self):
        self.assertEqual(self._get(RANGE, login='aatt_office', password='OfficePass1!').status_code, 200)

    # -- summary ---------------------------------------------------------------

    def test_summary_counts_and_totals(self):
        resp = self._get(RANGE)
        rows = self._rows(resp)
        data = resp.json()['data']
        self.assertEqual(set(rows), {self.alice.id, self.bob.id, self.dan.id})  # Cara has no marks
        alice = rows[self.alice.id]
        self.assertEqual((alice['total'], alice['present'], alice['absent']), (4, 3, 1))
        self.assertEqual(alice['percentage'], 75.0)
        self.assertEqual(alice['class']['id'], self.course.id)
        self.assertEqual(alice['section']['id'], self.batch.id)
        self.assertEqual(alice['roll_number'], '1')
        bob = rows[self.bob.id]
        self.assertEqual((bob['total'], bob['late'], bob['absent'], bob['percentage']), (2, 1, 1, 0.0))
        self.assertEqual(data['totals'], {
            'students': 3, 'marked': 7, 'present': 4, 'absent': 2, 'late': 1, 'excused': 0, 'percentage': 57.1,
        })
        self.assertEqual((data['date_from'], data['date_to'], data['view']), ('2026-03-02', '2026-03-04', 'summary'))
        self.assertEqual(resp.json()['meta']['total'], 3)

    def test_summary_matches_per_student_summary(self):
        rows = self._rows(self._get(RANGE))
        resp = self.url_open(
            f'/api/v1/attendance/students/{self.alice.id}/summary?{RANGE}',
            headers=self._headers('aatt_coord', 'CoordPass1!'))
        summary = resp.json()['data']['summary']
        for key in ('total', 'present', 'absent', 'late', 'excused', 'percentage'):
            self.assertEqual(rows[self.alice.id][key], summary[key], key)

    def test_timezone_boundary(self):
        """The late-night scan counts on the user's local date."""
        self.assertEqual(self._rows(self._get('date_from=2026-03-02&date_to=2026-03-03'))[self.alice.id]['total'], 3)
        rows = self._rows(self._get('date_from=2026-03-04&date_to=2026-03-04'))
        self.assertEqual(set(rows), {self.alice.id})
        self.assertEqual(rows[self.alice.id]['present'], 1)

    def test_summary_filters(self):
        rows = self._rows(self._get(f'{RANGE}&class_id={self.other_course.id}'))
        self.assertEqual(set(rows), {self.dan.id})
        rows = self._rows(self._get(f'{RANGE}&section_id={self.batch.id}&subject_id={self.other_subject.id}'))
        self.assertEqual(set(rows), {self.alice.id})
        self.assertEqual(rows[self.alice.id]['absent'], 1)
        self.assertEqual(set(self._rows(self._get(f'{RANGE}&q=bob'))), {self.bob.id})
        self.assertEqual(set(self._rows(self._get(f'{RANGE}&q=AATT-004'))), {self.dan.id})
        self.assertEqual(set(self._rows(self._get(f'{RANGE}&student_id={self.alice.id}'))), {self.alice.id})

    def test_include_unmarked_and_max_percentage(self):
        rows = self._rows(self._get(f'{RANGE}&class_id={self.course.id}&include_unmarked=1'))
        self.assertEqual(set(rows), {self.alice.id, self.bob.id, self.cara.id})
        self.assertEqual((rows[self.cara.id]['total'], rows[self.cara.id]['percentage']), (0, 0.0))
        # Low-attendance list: unmarked students are not "below" anything.
        rows = self._rows(self._get(f'{RANGE}&include_unmarked=1&max_percentage=75'))
        self.assertEqual(set(rows), {self.alice.id, self.bob.id})

    def test_summary_sort_and_paging(self):
        resp = self._get(f'{RANGE}&sort=percentage desc&limit=2')
        self.assertEqual([r['student']['id'] for r in resp.json()['data']['students']], [self.dan.id, self.alice.id])
        self.assertEqual(resp.json()['meta'], {'total': 3, 'limit': 2, 'offset': 0})
        resp = self._get(f'{RANGE}&sort=percentage desc&limit=2&offset=2')
        self.assertEqual([r['student']['id'] for r in resp.json()['data']['students']], [self.bob.id])
        resp = self._get(f'{RANGE}&sort=class')
        self.assertEqual([r['student']['id'] for r in resp.json()['data']['students']],
                         [self.alice.id, self.bob.id, self.dan.id])

    # -- records ---------------------------------------------------------------

    def test_records_newest_first(self):
        resp = self._get(f'{RANGE}&view=records&student_id={self.alice.id}')
        self.assertEqual(resp.status_code, 200, resp.text)
        records = resp.json()['data']['records']
        self.assertEqual([(r['date'], r['status']) for r in records], [
            ('2026-03-04', 'present'), ('2026-03-03', 'present'), ('2026-03-02', 'absent'), ('2026-03-02', 'present'),
        ])
        self.assertEqual(records[0]['id'], self.late_scan.id)
        self.assertIsNone(records[0]['session_id'])
        self.assertEqual(records[1]['subject']['id'], self.subject.id)
        self.assertEqual(records[1]['teacher']['id'], self.faculty.id)
        self.assertEqual(records[1]['class']['id'], self.course.id)
        resp = self._get(f'{RANGE}&view=records&student_id={self.alice.id}&sort=date asc&limit=1&offset=1')
        self.assertEqual([r['status'] for r in resp.json()['data']['records']], ['absent'])
        self.assertEqual(resp.json()['meta']['total'], 4)

    def test_records_status_filter(self):
        resp = self._get(f'{RANGE}&view=records&status=absent')
        records = resp.json()['data']['records']
        self.assertEqual({(r['student']['id'], r['date']) for r in records},
                         {(self.alice.id, '2026-03-02'), (self.bob.id, '2026-03-03')})
        self.assertEqual(resp.json()['meta']['total'], 2)

    # -- validation ------------------------------------------------------------

    def test_validation_errors(self):
        for query, code in (
            ('view=grid', 'invalid_view'),
            ('date_from=2026-13-01', 'invalid_date_from'),
            ('date_from=2026-03-05&date_to=2026-03-01', 'invalid_date_range'),
            ('date_from=2025-01-01&date_to=2026-03-01', 'range_too_large'),
            (f'{RANGE}&status=absent', 'invalid_status'),
            (f'{RANGE}&view=records&status=sick', 'invalid_status'),
            (f'{RANGE}&class_id=999999', 'invalid_class_id'),
            (f'{RANGE}&sort=age', 'invalid_sort'),
            (f'{RANGE}&max_percentage=low', 'invalid_max_percentage'),
        ):
            resp = self._get(query)
            self.assertEqual(resp.status_code, 400, query)
            self.assertEqual(resp.json()['error']['code'], code, query)
