# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import datetime, timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSchoolEvent(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.venue = cls.env['bxi.event.venue'].create({
            'name': 'Main Auditorium', 'code': 'AUD', 'capacity': 200,
        })
        cls.student = cls.env['op.student'].create({
            'first_name': 'Test', 'last_name': 'Student', 'gr_no': 'EVT-001', 'gender': 'm',
        })

    def _make_event(self, start, end, venue=None):
        return self.env['event.event'].create({
            'name': 'Test Event',
            'date_begin': start,
            'date_end': end,
            'venue_id': venue.id if venue else False,
        })

    def test_venue_overlap_blocked(self):
        start = datetime(2026, 9, 1, 10, 0)
        self._make_event(start, start + timedelta(hours=2), self.venue)
        with self.assertRaises(ValidationError):
            self._make_event(start + timedelta(hours=1), start + timedelta(hours=3), self.venue)

    def test_venue_non_overlap_allowed(self):
        start = datetime(2026, 9, 1, 10, 0)
        self._make_event(start, start + timedelta(hours=2), self.venue)
        # Starts exactly when the first event ends, so both bookings stand.
        second = self._make_event(start + timedelta(hours=2), start + timedelta(hours=4), self.venue)
        self.assertEqual(self.env['event.event'].search_count([('venue_id', '=', self.venue.id)]), 2)
        self.assertEqual(second.venue_id, self.venue)

    def test_paid_event_blocks_confirm_without_payment(self):
        income_account = self.env['account.account'].search([
            ('account_type', '=', 'income'),
        ], limit=1)
        product = self.env['product.product'].create({
            'name': 'Workshop Fee',
            'lst_price': 100.0,
            'property_account_income_id': income_account.id,
        })
        event = self._make_event(
            datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 12, 0))
        event.write({'is_paid_event': True, 'fee_product_id': product.id})
        registration = self.env['event.registration'].create({
            'event_id': event.id,
            'student_id': self.student.id,
            'partner_id': self.student.partner_id.id,
        })
        # Confirming without payment must be blocked (UserError), but the
        # invoice itself is still generated as part of that attempt and
        # must survive the failure. Odoo's self.assertRaises() wraps its
        # block in a savepoint that gets rolled back once the expected
        # exception is caught (see BaseCase._assertRaises), which would
        # silently undo the invoice creation along with the error - so the
        # call is made through a plain try/except here instead.
        try:
            registration.action_confirm()
            self.fail('action_confirm() should have raised UserError.')
        except UserError:
            pass
        self.assertTrue(registration.invoice_id)
        # event.registration's own default state is already 'open' (base
        # `event` treats that as "registered", not "confirmed" - see
        # event_registration.py state field help text); action_confirm()
        # only ever writes 'open' again via super(). So a blocked
        # confirmation simply never gets past the payment guard - it does
        # not move the record to some separate 'draft' state, which this
        # module's state selection doesn't even have as an initial value.
        self.assertEqual(registration.state, 'open')

    def test_bulk_registration_wizard(self):
        event = self._make_event(datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 12, 0))
        wizard = self.env['event.bulk.registration.wizard'].create({
            'event_id': event.id,
            'student_ids': [(6, 0, [self.student.id])],
        })
        wizard.action_create_registrations()
        self.assertEqual(len(event.registration_ids), 1)
        self.assertEqual(event.registration_ids.student_id, self.student)

    def test_paid_event_needs_fee_product(self):
        event = self._make_event(datetime(2026, 9, 2, 10, 0), datetime(2026, 9, 2, 12, 0))
        with self.assertRaises(ValidationError):
            event.write({'is_paid_event': True})

    def test_permission_slip_gates_confirmation(self):
        event = self._make_event(datetime(2026, 9, 3, 10, 0), datetime(2026, 9, 3, 12, 0))
        event.requires_permission_slip = True
        registration = self.env['event.registration'].create({
            'event_id': event.id, 'student_id': self.student.id, 'partner_id': self.student.partner_id.id})
        with self.assertRaises(UserError):
            registration.action_confirm()
        registration.action_sign_permission_slip('A Parent')
        self.assertTrue(registration.permission_slip_signed)
        self.assertEqual(registration.signed_by, 'A Parent')
        self.assertTrue(registration.signed_date)
        registration.action_confirm()
        self.assertEqual(registration.state, 'open')

    def test_over_capacity_flag(self):
        event = self._make_event(datetime(2026, 9, 4, 10, 0), datetime(2026, 9, 4, 12, 0), self.venue)
        event.write({'seats_limited': True, 'seats_max': 150})
        self.assertFalse(event.over_capacity)
        event.seats_max = 250
        self.assertTrue(event.over_capacity)

    def test_participation_certificates(self):
        event = self._make_event(datetime(2026, 9, 5, 10, 0), datetime(2026, 9, 5, 12, 0))
        cert_type = self.env['op.certificate.type'].create({'name': 'Participation', 'code': 'EVT-PART'})
        registration = self.env['event.registration'].create({
            'event_id': event.id, 'student_id': self.student.id, 'partner_id': self.student.partner_id.id})
        # Only checked-in attendees get one.
        with self.assertRaises(UserError):
            event.action_generate_participation_certificates(cert_type.id)
        registration.state = 'done'
        event.action_generate_participation_certificates(cert_type.id)
        self.assertEqual(registration.certificate_id.student_id, self.student)
        self.assertEqual(registration.certificate_id.certificate_type_id, cert_type)
        # Running it again doesn't issue a second certificate.
        with self.assertRaises(UserError):
            event.action_generate_participation_certificates(cert_type.id)

    def test_post_announcement_once(self):
        event = self._make_event(datetime(2026, 9, 6, 10, 0), datetime(2026, 9, 6, 12, 0))
        event.action_post_announcement()
        announcement = event.announcement_id
        self.assertEqual((announcement.title, announcement.category), ('Test Event', 'event'))
        event.action_post_announcement()
        self.assertEqual(event.announcement_id, announcement)
        self.assertEqual(self.env['bxi.announcement'].search_count([('title', '=', 'Test Event')]), 1)

    def test_ptm_converts_to_event(self):
        course = self.env['op.course'].create({'name': 'Event PTM Class', 'code': 'EVT-PTM'})
        meeting = self.env['bxi.ptm.meeting'].create({
            'name': 'Term 1 PTM', 'start_datetime': datetime(2026, 9, 7, 9, 0),
            'end_datetime': datetime(2026, 9, 7, 12, 0), 'venue': 'Hall B', 'class_ids': [(6, 0, course.ids)]})
        meeting.action_convert_to_event()
        event = meeting.event_id
        self.assertEqual((event.name, event.event_category), ('Term 1 PTM', 'ptm'))
        self.assertEqual(event.course_ids, course)
        self.assertIn('Venue: Hall B', event.note)  # an HTML field
        # Converting again keeps the same event.
        meeting.action_convert_to_event()
        self.assertEqual(meeting.event_id, event)
