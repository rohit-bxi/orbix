from datetime import datetime, timedelta

from odoo.exceptions import ValidationError
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
        # Should not raise: starts exactly when the first event ends.
        self._make_event(start + timedelta(hours=2), start + timedelta(hours=4), self.venue)

    def test_paid_event_blocks_confirm_without_payment(self):
        product = self.env['product.product'].create({'name': 'Workshop Fee', 'lst_price': 100.0})
        event = self._make_event(
            datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 12, 0))
        event.write({'is_paid_event': True, 'fee_product_id': product.id})
        registration = self.env['event.registration'].create({
            'event_id': event.id,
            'student_id': self.student.id,
            'partner_id': self.student.partner_id.id,
        })
        registration.action_confirm()
        self.assertTrue(registration.invoice_id)
        self.assertEqual(registration.state, 'draft')

    def test_bulk_registration_wizard(self):
        event = self._make_event(datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 12, 0))
        wizard = self.env['event.bulk.registration.wizard'].create({
            'event_id': event.id,
            'student_ids': [(6, 0, [self.student.id])],
        })
        wizard.action_create_registrations()
        self.assertEqual(len(event.registration_ids), 1)
        self.assertEqual(event.registration_ids.student_id, self.student)
