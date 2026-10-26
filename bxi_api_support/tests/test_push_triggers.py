# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportPushTriggers(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course, cls.batch = cls._create_class('PUSH')
        cls.parent_user = mail_new_test_user(
            cls.env, login='push_parent', groups='base.group_portal', password='ParentPass1!')
        cls.teacher_user = mail_new_test_user(
            cls.env, login='push_teacher', groups='base.group_user,openeducat_core.group_op_faculty',
            password='TeacherPass1!')
        cls.student = cls._create_student('PUSH-001', first_name='Push', last_name='Kid')
        cls._enroll(cls.student, cls.course, cls.batch)
        cls.parent = cls._create_parent(cls.parent_user, cls.student)
        cls.faculty = cls._create_faculty(cls.teacher_user, first_name='Push')
        cls.subject = cls.env['op.subject'].create({'name': 'Push Subject', 'code': 'PUSHS'})

    def _inbox(self, user, category):
        return self.env['bxi.notification'].search([('user_id', '=', user.id), ('category', '=', category)])

    def test_push_announcement_reaches_parents_of_targeted_class(self):
        announcement = self.env['bxi.announcement'].create({
            'title': 'Sports day', 'body': 'Friday', 'target_audience': 'specific_class',
            'course_ids': [(6, 0, self.course.ids)], 'channel_push': True,
        })
        announcement.action_publish()
        self.assertEqual(len(self._inbox(self.parent_user, 'announcement')), 1)

    def test_announcement_without_push_channel_is_silent(self):
        announcement = self.env['bxi.announcement'].create({
            'title': 'Quiet', 'body': 'x', 'target_audience': 'all_parents', 'channel_push': False,
        })
        announcement.action_publish()
        self.assertFalse(self._inbox(self.parent_user, 'announcement'))

    def test_new_message_notifies_the_other_side_only(self):
        thread = self.env['bxi.message.thread'].create({
            'student_id': self.student.id, 'parent_id': self.parent.id, 'teacher_id': self.faculty.id,
            'subject': 'Homework',
        })
        self.env['bxi.message'].create({
            'thread_id': thread.id, 'sender_user_id': self.parent_user.id, 'body': 'Hello teacher'})
        self.assertEqual(len(self._inbox(self.teacher_user, 'message')), 1)
        self.assertFalse(self._inbox(self.parent_user, 'message'))

    def _session(self, start):
        return self.env['op.session'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id, 'subject_id': self.subject.id,
            'faculty_id': self.faculty.id, 'start_datetime': start, 'end_datetime': start + timedelta(hours=1),
        })

    def test_absence_today_notifies_family_once_per_day(self):
        now = fields.Datetime.now().replace(minute=0, second=0)
        for offset in (0, 1):
            session = self._session(now - timedelta(hours=offset + 1))
            if session.session_date != fields.Date.context_today(session):
                return  # test running right after midnight UTC - nothing meaningful to check
            stamp = session.start_datetime
            self.env['hr.attendance'].create({
                'employee_id': self.student.employee_id.id, 'session_id': session.id, 'status': 'absent',
                'check_in': stamp, 'check_out': stamp,
            })
        self.assertEqual(len(self._inbox(self.parent_user, 'absence')), 1)

    def test_absence_for_a_past_day_or_history_import_is_silent(self):
        session = self._session(fields.Datetime.now() - timedelta(days=5))
        self.env['hr.attendance'].create({
            'employee_id': self.student.employee_id.id, 'session_id': session.id, 'status': 'absent',
            'check_in': session.start_datetime, 'check_out': session.start_datetime,
        })
        today = self._session(fields.Datetime.now().replace(hour=0, minute=30))
        self.env['hr.attendance'].with_context(bxi_no_notify=True).create({
            'employee_id': self.student.employee_id.id, 'session_id': today.id, 'status': 'absent',
            'check_in': today.start_datetime, 'check_out': today.start_datetime,
        })
        self.assertFalse(self._inbox(self.parent_user, 'absence'))

    def test_fee_due_reminder_sent_once(self):
        detail = self.env['op.student.fees.details'].create({
            'student_id': self.student.id, 'amount': 500.0,
            'date': fields.Date.today() + timedelta(days=2),
        })
        self.assertTrue(detail.amount_pending)
        Details = self.env['op.student.fees.details']
        Details._cron_bxi_fee_due_reminders()
        Details._cron_bxi_fee_due_reminders()
        self.assertEqual(len(self._inbox(self.parent_user, 'fee_due')), 1)
