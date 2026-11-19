# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The Schedule PTM and Edit Schedule PTM screens: date + time in the
school's time zone, venue, and section chips ("Class 10 A")."""
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase

URL = '/api/v1/academic/ptm-meetings'


@tagged('post_install', '-at_install')
class TestPtmScreenApi(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mail_new_test_user(cls.env, login='ptms_coord', password='CoordPass1!',
                           groups='base.group_user,bxi_academic_management.group_academic_coordinator')
        parent_a = mail_new_test_user(cls.env, login='ptms_parent_a', password='ParentPass1!',
                                      groups='base.group_portal')
        parent_b = mail_new_test_user(cls.env, login='ptms_parent_b', password='ParentPass1!',
                                      groups='base.group_portal')
        cls.class10, cls.sec_a = cls._create_class('PTMS10')
        cls.sec_b = cls.env['op.batch'].create({
            'name': 'PTMS10 B', 'code': 'PTMS10-B2', 'course_id': cls.class10.id,
            'start_date': '2026-01-01', 'end_date': '2027-12-31'})
        cls.class9, cls.sec_9a = cls._create_class('PTMS9')
        cls.student_a = cls._create_student('PTMS-A')
        cls._enroll(cls.student_a, cls.class10, cls.sec_a)
        cls.student_b = cls._create_student('PTMS-B')
        cls._enroll(cls.student_b, cls.class10, cls.sec_b)
        cls.parent_a = cls._create_parent(parent_a, cls.student_a)
        cls.parent_b = cls._create_parent(parent_b, cls.student_b)
        cls.env.company.resource_calendar_id.tz = 'Asia/Kolkata'

    def _post(self, url, body):
        return self.url_open(url, headers=self._headers('ptms_coord', 'CoordPass1!'), json=body, method='POST')

    def _error(self, resp, status, code):
        self.assertEqual(resp.status_code, status, resp.text)
        self.assertEqual(resp.json()['error']['code'], code)

    def _create(self, **overrides):
        body = {'name': 'First Term PTM', 'date': '25/05/2026', 'time': '10 : 15 : AM', 'venue': 'Main Auditorium',
                'section_ids': [self.sec_b.id, self.sec_a.id]}
        body.update(overrides)
        # None drops a key (e.g. sections typed instead of section_ids).
        return self._post(URL, {key: value for key, value in body.items() if value is not None})

    def _my_meetings(self, login):
        resp = self.url_open(URL + '/my?include_past=1', headers=self._headers(login, 'ParentPass1!'))
        return [m['id'] for m in resp.json()['data']['meetings']]

    def test_schedule_ptm(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertEqual((data['name'], data['venue']), ('First Term PTM', 'Main Auditorium'))
        self.assertEqual((data['date'], data['time'], data['time_label'], data['duration_minutes']),
                         ('2026-05-25', '10:15', '10:15 AM', 60))
        self.assertEqual(data['start_datetime'], '2026-05-25T04:45:00', 'Stored in UTC (IST is +5:30).')
        self.assertEqual(sorted(data['section_ids']), sorted([self.sec_a.id, self.sec_b.id]))
        self.assertEqual(data['class_ids'], [self.class10.id], "A section's class is added for it.")
        self.assertEqual(data['parents_notified'], 2)

        # Typed chips, a 24-hour time and a longer meeting.
        typed = self._create(name='Class 9 PTM', section_ids=None, sections='PTMS9 Section', time='16:30',
                             duration_minutes=90)
        self.assertEqual(typed.status_code, 201, typed.text)
        typed = typed.json()['data']
        self.assertEqual((typed['time_label'], typed['duration_minutes'], typed['section_ids']),
                         ('04:30 PM', 90, [self.sec_9a.id]))

    def test_only_chosen_sections_are_invited(self):
        data = self._create(section_ids=[self.sec_a.id]).json()['data']
        self.assertEqual(data['parents_notified'], 1)
        self.assertIn(data['id'], self._my_meetings('ptms_parent_a'))
        self.assertNotIn(data['id'], self._my_meetings('ptms_parent_b'), 'Class 10 B was not invited.')
        calendar = self.url_open('/api/v1/calendar?student_id=%s&date_from=2026-05-01&date_to=2026-05-31'
                                 % self.student_b.id, headers=self._headers('ptms_parent_b', 'ParentPass1!'))
        self.assertNotIn(data['id'], [i['id'] for i in calendar.json()['data']['items'] if i['type'] == 'ptm'])

        # A whole class (no section chosen) still invites everyone, as before.
        whole = self._create(name='Whole Class PTM', section_ids=None, class_ids=[self.class10.id]).json()['data']
        self.assertEqual((whole['parents_notified'], whole['section_ids']), (2, []))

    def test_required_fields(self):
        for key in ('name', 'venue', 'date', 'time'):
            body = {'name': 'X', 'date': '25/05/2026', 'time': '10:15 AM', 'venue': 'Hall',
                    'section_ids': [self.sec_a.id]}
            body.pop(key)
            self._error(self._post(URL, body), 400, 'missing_%s' % key)
        self._error(self._create(section_ids=None), 400, 'missing_class_ids')
        self._error(self._create(section_ids=[]), 400, 'missing_class_ids')
        self._error(self._create(time='25:00'), 400, 'invalid_time')
        self._error(self._create(time='13:15 PM'), 400, 'invalid_time')
        self._error(self._create(date='31/02/2026'), 400, 'invalid_date')
        self._error(self._create(venue='  '), 400, 'missing_venue')
        self._error(self._create(sections=['No Such Section'], section_ids=None), 400, 'unknown_section')

    def test_edit_ptm(self):
        data = self._create(duration_minutes=45).json()['data']
        url = URL + '/%s/update' % data['id']
        # Edit screen: a new time keeps the meeting's length; the date stays.
        resp = self._post(url, {'time': '11:00 AM', 'venue': 'Library'})
        self.assertEqual(resp.status_code, 200, resp.text)
        moved = resp.json()['data']
        self.assertEqual((moved['date'], moved['time'], moved['duration_minutes'], moved['venue']),
                         ('2026-05-25', '11:00', 45, 'Library'))
        moved = self._post(url, {'date': '2026-05-26'}).json()['data']
        self.assertEqual((moved['date'], moved['time']), ('2026-05-26', '11:00'))

        # The chips' x: take Class 10 B off; then add a Class 9 section.
        chips = self._post(url, {'remove_section_ids': [self.sec_b.id]}).json()['data']
        self.assertEqual((chips['section_ids'], chips['parents_notified']), ([self.sec_a.id], 1))
        chips = self._post(url, {'add_section_ids': [self.sec_9a.id]}).json()['data']
        self.assertEqual(sorted(chips['class_ids']), sorted([self.class10.id, self.class9.id]))
        # Removing the last chip is refused.
        self._error(self._post(url, {'section_ids': []}), 400, 'missing_class_ids')
        # Taking a class off takes its sections with it.
        chips = self._post(url, {'class_ids': [self.class9.id]}).json()['data']
        self.assertEqual((chips['class_ids'], chips['section_ids']), ([self.class9.id], [self.sec_9a.id]))
