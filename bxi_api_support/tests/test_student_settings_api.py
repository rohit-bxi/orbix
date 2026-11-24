# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Settings screen (/me/preferences), the reminders its switches control,
and the Career Pathway report with opt-in app usage."""
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestStudentSettingsApi(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student_user = mail_new_test_user(cls.env, login='ss_student', password='StudentPass1!',
                                              groups='base.group_portal')
        cls.parent_user = mail_new_test_user(cls.env, login='ss_parent', password='ParentPass1!',
                                             groups='base.group_portal')
        cls.teacher_user = mail_new_test_user(cls.env, login='ss_teacher', password='TeacherPass1!',
                                              groups='base.group_user,openeducat_core.group_op_faculty')
        cls.course, cls.section = cls._create_class('SS9')
        cls.maths = cls.env['op.subject'].create({'name': 'SS Mathematics', 'code': 'SS-MATH'})
        cls.student = cls._create_student('SS-001', first_name='Sam', last_name='Rao', user=cls.student_user)
        cls._enroll(cls.student, cls.course, cls.section)
        cls._create_parent(cls.parent_user, cls.student)
        cls.teacher = cls._create_faculty(cls.teacher_user)
        cls.Notification = cls.env['bxi.notification'].sudo()

    def _get(self, url, login='ss_student', password='StudentPass1!'):
        return self.url_open(url, headers=self._headers(login, password))

    def _post(self, url, body, login='ss_student', password='StudentPass1!'):
        return self.url_open(url, headers=self._headers(login, password), json=body, method='POST')

    def _data(self, resp):
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()['data']

    def _error(self, resp, status, code):
        self.assertEqual(resp.status_code, status, resp.text)
        self.assertEqual(resp.json()['error']['code'], code)

    # -- preferences ----------------------------------------------------------------

    def test_preferences(self):
        data = self._data(self._get('/api/v1/me/preferences'))
        self.assertEqual(data['notifications'], {'assignment_reminders': True, 'exam_notifications': True,
                                                 'grade_updates': True, 'study_reminders': True})
        self.assertEqual(data['app'], {'language': 'en_US', 'theme': 'auto', 'offline_mode': False,
                                       'auto_sync': True})
        updated = self._data(self._post('/api/v1/me/preferences', {
            'notifications': {'grade_updates': False}, 'app': {'theme': 'dark', 'offline_mode': True}}))
        self.assertFalse(updated['notifications']['grade_updates'])
        self.assertTrue(updated['notifications']['exam_notifications'], 'Keys not sent keep their value.')
        self.assertEqual((updated['app']['theme'], updated['app']['offline_mode']), ('dark', True))
        self.assertEqual(self.student_user.bxi_muted_notification_categories, 'result')

        self._error(self._post('/api/v1/me/preferences', {'notifications': {'spam': False}}), 400,
                    'invalid_notification_setting')
        self._error(self._post('/api/v1/me/preferences', {'app': {'theme': 'pink'}}), 400, 'invalid_theme')
        self._error(self._post('/api/v1/me/preferences', {'app': {'language': 'xx_XX'}}), 400, 'invalid_language')
        self._error(self._post('/api/v1/me/preferences', {'notifications': {'grade_updates': 'no'}}), 400,
                    'invalid_value')
        # Switching back on un-mutes.
        self._data(self._post('/api/v1/me/preferences', {'notifications': {'grade_updates': True}}))
        self.assertFalse(self.student_user.bxi_muted_notification_categories)

    def test_muted_category_skips_push_only(self):
        self.student_user._bxi_set_notification_switches({'exam_notifications': False})
        muted, normal = self.Notification._notify(self.student_user | self.parent_user, 'Exam scheduled', category='exam')
        by_user = {n.user_id: n for n in muted | normal}
        self.assertEqual(by_user[self.student_user].push_state, 'disabled')
        self.assertEqual(by_user[self.parent_user].push_state, 'pending', "A parent's own settings apply to them.")
        other = self.Notification._notify(self.student_user, 'Homework', category='homework')
        self.assertEqual(other.push_state, 'pending')

    # -- reminders ------------------------------------------------------------------------

    def _homework(self, name, due):
        assignment_type = self.env['grading.assignment.type'].search([], limit=1) or \
            self.env['grading.assignment.type'].create({'name': 'SS Homework', 'code': 'SSHW'})
        assignment = self.env['op.assignment'].create({
            'name': name, 'course_id': self.course.id, 'batch_id': self.section.id, 'subject_id': self.maths.id,
            'faculty_id': self.teacher.id, 'assignment_type': assignment_type.id,
            'issued_date': fields.Datetime.now() - timedelta(days=2), 'submission_date': due,
            'description': 'x', 'allocation_ids': [(6, 0, self.student.ids)]})
        assignment.act_publish()
        return assignment

    def test_homework_and_study_reminders(self):
        self.env.company.resource_calendar_id.tz = 'Asia/Kolkata'
        now = fields.Datetime.now()
        due_soon = self._homework('SS Fractions', now + timedelta(hours=10))
        self._homework('SS Later', now + timedelta(days=4))
        handed_in = self._homework('SS Done', now + timedelta(hours=5))
        self.env['op.assignment.sub.line'].create({'assignment_id': handed_in.id, 'student_id': self.student.id,
                                                   'description': 'done', 'state': 'submit'})
        Assignment = self.env['op.assignment']
        Assignment._cron_bxi_homework_reminders()
        reminders = self.Notification.search([('category', '=', 'homework_reminder')])
        self.assertEqual(set(reminders.mapped('res_id')), {due_soon.id})
        self.assertEqual(reminders.user_id, self.student_user | self.parent_user)
        # School time, not UTC: due 10 hours from now in Asia/Kolkata.
        local_due = fields.Datetime.context_timestamp(self.env['res.users'].with_context(tz='Asia/Kolkata'),
                                                      due_soon.submission_date)
        self.assertIn(local_due.strftime('%I:%M %p'), reminders[0].body)
        self.assertNotIn(fields.Datetime.to_string(due_soon.submission_date), reminders[0].body)
        Assignment._cron_bxi_homework_reminders()
        self.assertEqual(self.Notification.search_count([('category', '=', 'homework_reminder')]), 2, 'Once only.')

        self.env['op.student']._cron_bxi_study_reminders()
        study = self.Notification.search([('category', '=', 'study_reminder')])
        self.assertEqual(study.user_id, self.student_user, 'Students only, not parents.')
        self.assertIn('homework', study.body)
        self.env['op.student']._cron_bxi_study_reminders()
        self.assertEqual(len(self.Notification.search([('category', '=', 'study_reminder')])), 1, 'Once a day.')

        # The Notifications screen files both under Assignments.
        tab = self._data(self._get('/api/v1/notifications?tab=assignments'))
        categories = {n['category'] for n in tab['notifications']}
        self.assertTrue({'homework_reminder', 'study_reminder'} <= categories, tab)

    # -- career report ------------------------------------------------------------------------

    def test_career_report_and_usage(self):
        report = self._data(self._get('/api/v1/student/career-report'))
        self.assertFalse(report['consent']['consent'])
        self.assertIsNone(report['usage'])

        usage = {'categories': [{'category': 'development', 'minutes': 120, 'app_count': 5},
                                {'category': 'social', 'minutes': 60, 'app_count': 8},
                                {'category': 'games', 'minutes': 60, 'app_count': 3}]}
        self._error(self._post('/api/v1/student/usage', usage), 403, 'consent_required')
        # The student can't consent for themself; a teacher can't either.
        self._error(self._post('/api/v1/student/usage/consent', {'consent': True}), 403, 'parent_consent_required')
        self._error(self._post('/api/v1/student/usage/consent', {'student_id': self.student.id, 'consent': True},
                               'ss_teacher', 'TeacherPass1!'), 403, 'forbidden')
        consent = self._data(self._post('/api/v1/student/usage/consent', {'consent': True},
                                        'ss_parent', 'ParentPass1!'))
        self.assertTrue(consent['consent'])
        self.assertEqual(consent['given_by']['id'], self.parent_user.id)

        self.assertEqual(self._data(self._post('/api/v1/student/usage', usage))['saved'], 3)
        yesterday = fields.Date.to_string(fields.Date.today() - timedelta(days=1))
        self._data(self._post('/api/v1/student/usage', {'date': yesterday, 'categories': [
            {'category': 'development', 'minutes': 60, 'app_count': 4}]}))
        # Re-sending a day replaces it.
        self._data(self._post('/api/v1/student/usage', usage))
        self.assertEqual(self.env['bxi.device.usage'].search_count([('student_id', '=', self.student.id)]), 4)
        self._error(self._post('/api/v1/student/usage', {'categories': [{'category': 'tiktok', 'minutes': 5}]}),
                    400, 'invalid_category')
        self._error(self._post('/api/v1/student/usage', {'categories': [{'category': 'games', 'minutes': 2000}]}),
                    400, 'invalid_value')
        self._error(self._post('/api/v1/student/usage', {'date': '2020-01-01', 'categories': usage['categories']}),
                    400, 'invalid_date')
        self._error(self._post('/api/v1/student/usage', usage, 'ss_parent', 'ParentPass1!'), 403, 'forbidden')

        report = self._data(self._get('/api/v1/student/career-report', 'ss_parent', 'ParentPass1!'))['usage']
        self.assertEqual(report['days_with_data'], 2)
        self.assertEqual(report['daily_screen_time_hours'], 2.5)  # (240 + 60) min / 2 days
        self.assertEqual(report['productivity_score'], 60)  # development 180 of 300
        self.assertEqual(report['primary_interest']['key'], 'development')
        self.assertEqual(report['primary_interest']['label'], 'Tech')
        self.assertEqual([c['category'] for c in report['category_analysis']], ['development', 'games', 'social'], 'Ties sort by key.')
        careers = self._data(self._get('/api/v1/student/career-report'))['careers']
        self.assertEqual(careers[0]['name'], 'Mobile App Developer')
        self.assertEqual(careers[0]['match'], 100)
        self.assertEqual(careers[0]['sources'], ['usage'])
        # Content Creator's main category is entertainment, unused here: design
        # or social time alone does not suggest it.
        self.assertNotIn('Content Creator', [c['name'] for c in careers])

        # Teachers don't see a student's app usage.
        self._error(self._get('/api/v1/student/career-report?student_id=%s' % self.student.id,
                              'ss_teacher', 'TeacherPass1!'), 403, 'forbidden')
        # The student may withdraw; stored usage is deleted.
        self.assertFalse(self._data(self._post('/api/v1/student/usage/consent', {'consent': False}))['consent'])
        self.assertFalse(self.env['bxi.device.usage'].search_count([('student_id', '=', self.student.id)]))
        self.assertIsNone(self._data(self._get('/api/v1/student/career-report'))['usage'])
