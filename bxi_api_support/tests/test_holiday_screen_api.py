# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The Add / Edit Holiday screens: DD/MM/YYYY dates as whole days in the
school's time zone, the same day shape everywhere, and duplicates."""
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase

URL = '/api/v1/calendar/holidays'


@tagged('post_install', '-at_install')
class TestHolidayScreenApi(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mail_new_test_user(cls.env, login='hol_coord', password='CoordPass1!',
                           groups='base.group_user,bxi_academic_management.group_academic_coordinator')
        mail_new_test_user(cls.env, login='hol_parent', password='ParentPass1!', groups='base.group_portal')
        # IST (UTC+5:30): a day starts at 18:30 UTC the evening before.
        cls.env.company.resource_calendar_id.tz = 'Asia/Kolkata'

    def _post(self, url, body):
        return self.url_open(url, headers=self._headers('hol_coord', 'CoordPass1!'), json=body, method='POST')

    def _get(self, url, login='hol_coord', password='CoordPass1!'):
        return self.url_open(url, headers=self._headers(login, password))

    def _error(self, resp, status, code):
        self.assertEqual(resp.status_code, status, resp.text)
        self.assertEqual(resp.json()['error']['code'], code)
        return resp.json()['error']

    def _create(self, **overrides):
        body = {'name': 'Independence Day', 'start_date': '15/08/2026', 'end_date': '15/08/2026',
                'description': 'National Holiday'}
        body.update(overrides)
        return self._post(URL, {key: value for key, value in body.items() if value is not None})

    def test_add_holiday(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertEqual((data['name'], data['description'], data['start_date'], data['end_date']),
                         ('Independence Day', 'National Holiday', '2026-08-15', '2026-08-15'))
        self.assertEqual(data['date_from'], '2026-08-14 18:30:00', 'The whole day in IST, stored in UTC.')

        # The Edit screen's pre-fill and the list show the school's day, not the UTC one.
        got = self._get(URL + '/%s' % data['id'], 'hol_parent', 'ParentPass1!')
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual((got.json()['data']['start_date'], got.json()['data']['end_date']),
                         ('2026-08-15', '2026-08-15'))
        listed = self._get(URL + '?date_from=2026-08-01&date_to=2026-08-31').json()['data']['holidays']
        row = next(h for h in listed if h['id'] == data['id'])
        self.assertEqual((row['start_date'], row['end_date']), ('2026-08-15', '2026-08-15'))

        # The older keys and ISO days still work.
        old = self._create(name='Diwali', start_date=None, end_date=None, date_from='2026-11-08',
                           date_to='2026-11-09')
        self.assertEqual(old.status_code, 201, old.text)
        self.assertEqual((old.json()['data']['start_date'], old.json()['data']['end_date']),
                         ('2026-11-08', '2026-11-09'))

    def test_required_fields_and_checks(self):
        for key in ('name', 'start_date', 'end_date'):
            self._error(self._create(**{key: None}), 400, 'missing_%s' % key)
        self._error(self._create(name='   '), 400, 'missing_name')
        self._error(self._create(start_date=''), 400, 'missing_start_date')
        self._error(self._create(start_date='31/02/2026'), 400, 'invalid_start_date')
        self._error(self._create(end_date='14/08/2026'), 400, 'invalid_dates')

        first = self._create().json()['data']
        error = self._error(self._create(name='independence day', start_date='14/08/2026', end_date='16/08/2026'),
                            409, 'holiday_exists')
        self.assertEqual(error['existing_holiday_id'], first['id'])
        self.assertEqual(self._create(start_date='15/08/2027', end_date='15/08/2027').status_code, 201,
                         'The same holiday next year is fine.')
        # Odoo allows one public holiday per day: say which one is there.
        error = self._error(self._create(name='Raksha Bandhan'), 409, 'holiday_overlaps')
        self.assertEqual(error['existing_holiday_id'], first['id'])
        self.assertEqual(self._create(name='Raksha Bandhan', start_date='16/08/2026', end_date='16/08/2026')
                         .status_code, 201, 'The next day does not overlap.')
        self._error(self._get(URL + '/999999'), 404, 'not_found')

    def test_holiday_over_double_approved_time_off(self):
        """hr_holidays puts the time off a new holiday overlaps back in its
        state, re-checking the current user's time-off rights: a
        coordinator who is no time-off officer used to get a 403."""
        leave_type = self.env['hr.leave.type'].create({
            'name': 'Hol Double Approval', 'requires_allocation': False, 'leave_validation_type': 'both',
            'request_unit': 'day'})
        employee = self.env['hr.employee'].create({'name': 'Hol Staff'})
        leave = self.env['hr.leave'].with_context(leave_skip_state_check=True).create({
            'employee_id': employee.id, 'holiday_status_id': leave_type.id,
            'request_date_from': '2026-10-01', 'request_date_to': '2026-10-05'})
        leave.with_context(leave_skip_state_check=True).write({'state': 'validate'})
        self.assertEqual(leave.state, 'validate')

        resp = self._create(name='Gandhi Jayanti', start_date='02/10/2026', end_date='02/10/2026')
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(leave.state, 'validate', 'The time off keeps its approval.')
        holiday = resp.json()['data']['id']
        self.assertEqual(self._post(URL + '/%s/update' % holiday, {'end_date': '03/10/2026'}).status_code, 200)
        self.assertEqual(self._post(URL + '/%s/delete' % holiday, {}).status_code, 200)

    def test_edit_holiday(self):
        data = self._create().json()['data']
        url = URL + '/%s/update' % data['id']
        resp = self._post(url, {'end_date': '16/08/2026', 'description': 'Long weekend'})
        self.assertEqual(resp.status_code, 200, resp.text)
        result = resp.json()['data']
        self.assertEqual((result['start_date'], result['end_date'], result['description']),
                         ('2026-08-15', '2026-08-16', 'Long weekend'))
        self.assertIsNone(self._post(url, {'description': ''}).json()['data']['description'])
        self.assertEqual(self._post(url, {'name': 'Independence Day'}).status_code, 200,
                         'Re-saving its own name is not a duplicate of itself.')
        self._error(self._post(url, {'start_date': '17/08/2026'}), 400, 'invalid_dates')
        self._error(self._post(url, {'name': ''}), 400, 'missing_name')

        other = self._create(name='Janmashtami', start_date='04/09/2026', end_date='04/09/2026').json()['data']
        self._error(self._post(URL + '/%s/update' % other['id'], {'name': 'Independence Day',
                                                                   'start_date': '16/08/2026',
                                                                   'end_date': '16/08/2026'}),
                    409, 'holiday_exists')
