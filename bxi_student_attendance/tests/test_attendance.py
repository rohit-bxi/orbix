# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import date, datetime

from psycopg2 import IntegrityError

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestStudentAttendance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({
            'name': 'Test Course', 'code': 'ATC',
        })
        cls.batch = cls.env['op.batch'].create({
            'name': 'Batch A', 'code': 'ATB',
            'course_id': cls.course.id,
            'start_date': '2026-06-01', 'end_date': '2027-05-31',
        })
        cls.teacher = cls.env['op.faculty'].create({
            'first_name': 'John', 'last_name': 'Teacher',
            'birth_date': '1985-01-01', 'gender': 'male',
        })
        cls.subject = cls.env['op.subject'].create({
            'name': 'Mathematics', 'code': 'MTH',
        })
        cls.student = cls.env['op.student'].create({
            'first_name': 'Alice', 'last_name': 'Roe',
            'gr_no': 'ATT-001', 'gender': 'f',
            'course_detail_ids': [(0, 0, {
                'course_id': cls.course.id, 'batch_id': cls.batch.id,
            })],
        })
        cls.timing = cls.env['op.timing'].create({
            'name': 'Period 1', 'hour': '10', 'minute': '00',
            'am_pm': 'am', 'duration': 1.0,
        })
        cls.session = cls.env['op.session'].create({
            'start_datetime': datetime(2026, 9, 1, 10, 0),
            'end_datetime': datetime(2026, 9, 1, 11, 0),
            'course_id': cls.course.id,
            'faculty_id': cls.teacher.id,
            'batch_id': cls.batch.id,
            'subject_id': cls.subject.id,
        })

    def test_shadow_employee_created_on_student_create(self):
        self.assertTrue(self.student.employee_id)
        self.assertEqual(self.student.employee_id.employee_type, 'student')
        self.assertEqual(self.student.employee_id.student_id, self.student)

    def test_checkin_without_status_marks_present(self):
        attendance = self.env['hr.attendance'].create({
            'employee_id': self.student.employee_id.id,
            'check_in': datetime(2026, 9, 1, 9, 55),
        })
        self.assertEqual(attendance.status, 'present')

    def test_manual_absent_status_not_overridden(self):
        attendance = self.env['hr.attendance'].create({
            'employee_id': self.student.employee_id.id,
            'status': 'absent',
            'session_id': self.session.id,
        })
        self.assertEqual(attendance.status, 'absent')

    def test_duplicate_attendance_same_session_blocked(self):
        self.env['hr.attendance'].create({
            'employee_id': self.student.employee_id.id,
            'status': 'present',
            'session_id': self.session.id,
        })
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['hr.attendance'].create({
                'employee_id': self.student.employee_id.id,
                'status': 'late',
                'session_id': self.session.id,
            })

    def test_class_section_computed_from_running_enrollment(self):
        attendance = self.env['hr.attendance'].create({
            'employee_id': self.student.employee_id.id,
            'status': 'present',
            'session_id': self.session.id,
        })
        self.assertEqual(attendance.class_id, self.course)
        self.assertEqual(attendance.section_id, self.batch)

    def test_generate_sessions_from_timetable_creates_period(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'tuesday',
            'timing_id': self.timing.id,
            'subject_id': self.subject.id, 'teacher_id': self.teacher.id,
        })
        target_date = date(2026, 9, 1)  # a Tuesday
        self.assertEqual(target_date.strftime('%A').lower(), 'tuesday')
        created = self.env['op.session']._generate_from_timetable(target_date)
        self.assertEqual(len(created), 1)
        self.assertEqual(created.course_id, self.course)
        self.assertEqual(created.subject_id, self.subject)

    def test_generate_sessions_idempotent(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'tuesday',
            'timing_id': self.timing.id,
            'subject_id': self.subject.id, 'teacher_id': self.teacher.id,
        })
        target_date = date(2026, 9, 1)
        first = self.env['op.session']._generate_from_timetable(target_date)
        second = self.env['op.session']._generate_from_timetable(target_date)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)

    def test_generate_sessions_skips_lines_missing_subject_or_teacher(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'wednesday',
            'timing_id': self.timing.id,
        })
        target_date = date(2026, 9, 2)  # a Wednesday
        self.assertEqual(target_date.strftime('%A').lower(), 'wednesday')
        created = self.env['op.session']._generate_from_timetable(target_date)
        self.assertFalse(created)

    def test_timing_to_datetime_conversion(self):
        self.env.company.partner_id.tz = 'UTC'
        start, end = self.timing._to_datetime(date(2026, 9, 1))
        self.assertEqual(start, datetime(2026, 9, 1, 10, 0))
        self.assertEqual(end, datetime(2026, 9, 1, 11, 0))
