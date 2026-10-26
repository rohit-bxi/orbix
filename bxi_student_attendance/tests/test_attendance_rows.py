# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import date, datetime

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStudentAttendanceRows(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({'name': 'Rows Course', 'code': 'ROWC'})
        cls.batch = cls.env['op.batch'].create({
            'name': 'Rows Batch', 'code': 'ROWB', 'course_id': cls.course.id,
            'start_date': '2026-06-01', 'end_date': '2027-05-31',
        })
        cls.teacher = cls.env['op.faculty'].create({
            'first_name': 'Rows', 'last_name': 'Teacher', 'birth_date': '1985-01-01', 'gender': 'male',
        })
        cls.maths = cls.env['op.subject'].create({'name': 'Rows Maths', 'code': 'ROWM'})
        cls.science = cls.env['op.subject'].create({'name': 'Rows Science', 'code': 'ROWS'})
        cls.student = cls.env['op.student'].create({
            'first_name': 'Rowan', 'last_name': 'Pupil', 'gr_no': 'ROW-001', 'gender': 'm',
            'course_detail_ids': [(0, 0, {'course_id': cls.course.id, 'batch_id': cls.batch.id})],
        })

    def _session(self, start, subject):
        return self.env['op.session'].create({
            'start_datetime': start,
            'end_datetime': start.replace(hour=start.hour + 1),
            'course_id': self.course.id, 'batch_id': self.batch.id,
            'faculty_id': self.teacher.id, 'subject_id': subject.id,
        })

    def _mark(self, session, status):
        # Stamped at the period start: several same-student rows created
        # within one second can trip hr.attendance's overlap check.
        return self.env['hr.attendance'].create({
            'employee_id': self.student.employee_id.id, 'session_id': session.id, 'status': status,
            'check_in': session.start_datetime, 'check_out': session.start_datetime,
        })

    def test_hand_marked_row_is_dated_by_its_period_not_marking_time(self):
        # No check_in given: create() stamps the row with the marking time
        # (today), while its period was in September.
        session = self._session(datetime(2026, 9, 1, 9, 0), self.maths)
        self.env['hr.attendance'].create({
            'employee_id': self.student.employee_id.id, 'session_id': session.id, 'status': 'absent',
        })
        rows = self.student._get_attendance_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['date'], date(2026, 9, 1))
        self.assertEqual(rows[0]['subject'], 'Rows Maths')
        self.assertEqual(rows[0]['status'], 'absent')

    def test_date_range_filters_on_period_date(self):
        self._mark(self._session(datetime(2026, 9, 1, 9, 0), self.maths), 'present')
        self._mark(self._session(datetime(2026, 9, 5, 9, 0), self.maths), 'present')
        rows = self.student._get_attendance_rows(date(2026, 9, 2), date(2026, 9, 30))
        self.assertEqual([r['date'] for r in rows], [date(2026, 9, 5)])

    def test_summary_counts_and_day_rollup(self):
        self._mark(self._session(datetime(2026, 9, 1, 9, 0), self.maths), 'present')
        self._mark(self._session(datetime(2026, 9, 1, 10, 0), self.science), 'absent')
        self._mark(self._session(datetime(2026, 9, 2, 9, 0), self.maths), 'absent')
        self._mark(self._session(datetime(2026, 9, 3, 9, 0), self.maths), 'late')
        summary = self.student._summarize_attendance_rows(self.student._get_attendance_rows())
        self.assertEqual(summary['total'], 4)
        self.assertEqual(summary['present'], 1)
        self.assertEqual(summary['absent'], 2)
        self.assertEqual(summary['percentage'], 25.0)
        by_day = {d['date']: d['status'] for d in summary['days']}
        self.assertEqual(by_day, {
            date(2026, 9, 1): 'partial', date(2026, 9, 2): 'absent', date(2026, 9, 3): 'late',
        })

    def test_kiosk_scan_without_status_is_not_attendance(self):
        # A raw staff-style scan on the shadow employee still gets 'present'
        # from the create() override, so use a write to blank it out.
        attendance = self.env['hr.attendance'].create({
            'employee_id': self.student.employee_id.id,
            'check_in': datetime(2026, 9, 7, 8, 0), 'check_out': datetime(2026, 9, 7, 8, 0),
        })
        attendance.status = False
        self.assertEqual(self.student._get_attendance_rows(), [])

    def test_legacy_sheet_lines_are_copied_once_without_overwriting(self):
        session_copied = self._session(datetime(2026, 9, 10, 9, 0), self.maths)
        session_kept = self._session(datetime(2026, 9, 11, 9, 0), self.maths)
        self._mark(session_kept, 'present')
        register = self.env['op.attendance.register'].create({
            'name': 'Rows Register', 'code': 'ROWR', 'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        for session, flags in ((session_copied, {'absent': True}), (session_kept, {'absent': True})):
            sheet = self.env['op.attendance.sheet'].create({
                'register_id': register.id, 'session_id': session.id,
                'attendance_date': session.start_datetime.date(),
            })
            self.env['op.attendance.line'].create(dict(flags, attendance_id=sheet.id, student_id=self.student.id))

        copied, skipped, conflicts = self.env['hr.attendance']._copy_legacy_op_attendance()
        self.assertEqual((copied, conflicts), (1, 0))
        self.assertGreaterEqual(skipped, 1)
        by_date = {r['date']: r['status'] for r in self.student._get_attendance_rows()}
        self.assertEqual(by_date[date(2026, 9, 10)], 'absent')
        self.assertEqual(by_date[date(2026, 9, 11)], 'present', 'Existing hr.attendance must win.')

        # Running it again copies nothing new.
        copied_again, _skipped, _conflicts = self.env['hr.attendance']._copy_legacy_op_attendance()
        self.assertEqual(copied_again, 0)
