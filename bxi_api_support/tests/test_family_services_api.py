# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportFamilyServices(ApiSupportHttpCase):
    """Library, events, calendar, fee dues/receipts, transport card and
    PTMs from the family's side."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course, cls.batch = cls._create_class('FAM')
        cls.other_course, cls.other_batch = cls._create_class('FAMO')
        cls.student_user = mail_new_test_user(
            cls.env, login='fam_student', groups='base.group_portal', password='StudentPass1!')
        cls.parent_user = mail_new_test_user(
            cls.env, login='fam_parent', groups='base.group_portal', password='ParentPass1!')
        cls.other_parent_user = mail_new_test_user(
            cls.env, login='fam_other_parent', groups='base.group_portal', password='OtherPass1!')
        cls.librarian_user = mail_new_test_user(
            cls.env, login='fam_librarian', groups='base.group_user,openeducat_library.group_op_library_user',
            password='LibPass1!')
        cls.student = cls._create_student('FAM-001', user=cls.student_user)
        cls._enroll(cls.student, cls.course, cls.batch)
        cls.other_student = cls._create_student('FAM-002')
        cls._enroll(cls.other_student, cls.other_course, cls.other_batch)
        cls.parent = cls._create_parent(cls.parent_user, cls.student)
        cls._create_parent(cls.other_parent_user, cls.other_student)

    def _parent(self):
        return self._headers('fam_parent', 'ParentPass1!')

    # -- library --------------------------------------------------------------

    def _book(self):
        media = self.env['op.media'].create({
            'name': 'The Fam Book', 'isbn': '978-FAM',
            'author_ids': [(0, 0, {'name': 'Fam Author'})],
            'publisher_ids': [(0, 0, {'name': 'Fam Press'})],
            'genre_id': self.env['op.media.genre'].create({'name': 'Fam Fiction'}).id,
        })
        unit = self.env['op.media.unit'].create({'name': 'Copy 1', 'media_id': media.id})
        card_type = self.env['op.library.card.type'].create({
            'name': 'Fam Card', 'allow_media': 2, 'duration': 7, 'penalty_amt_per_day': 5.0,
        })
        self.env['op.library.card'].create({
            'partner_id': self.student.partner_id.id, 'library_card_type_id': card_type.id,
            'type': 'student', 'student_id': self.student.id,
        })
        return media, unit

    def test_library_issue_loans_and_return(self):
        media, unit = self._book()
        catalog = self.url_open('/api/v1/library/catalog?q=Fam Author', headers=self._parent()).json()
        self.assertIn(media.id, [i['id'] for i in catalog['data']['items']])

        # op.media.unit numbers its own barcodes on create.
        family_issue = self.url_open('/api/v1/library/issue', headers=self._parent(),
                                     json={'barcode': unit.barcode, 'student_id': self.student.id})
        self.assertEqual(family_issue.status_code, 403)
        librarian = self._headers('fam_librarian', 'LibPass1!')
        issue = self.url_open('/api/v1/library/issue', headers=librarian,
                              json={'barcode': unit.barcode, 'student_id': self.student.id})
        self.assertEqual(issue.status_code, 201, issue.text)
        loan_id = issue.json()['data']['id']

        loans = self.url_open(f'/api/v1/library/my-loans?student_id={self.student.id}', headers=self._parent()).json()
        self.assertEqual([l['id'] for l in loans['data']['loans']], [loan_id])
        self.assertEqual(self.url_open(
            f'/api/v1/library/my-loans?student_id={self.student.id}',
            headers=self._headers('fam_other_parent', 'OtherPass1!')).status_code, 403)

        late = fields.Date.to_string(fields.Date.today() + timedelta(days=10))
        returned = self.url_open(f'/api/v1/library/loans/{loan_id}/return', headers=librarian, json={'return_date': late})
        self.assertEqual(returned.status_code, 200, returned.text)
        self.assertEqual(returned.json()['data']['fine'], 15.0)
        history = self.url_open(f'/api/v1/library/history?student_id={self.student.id}', headers=self._parent()).json()
        self.assertEqual([l['id'] for l in history['data']['loans']], [loan_id])

    def test_reservation_student_only(self):
        media, _unit = self._book()
        self.assertEqual(self.url_open('/api/v1/library/reservations', headers=self._parent(),
                                       json={'media_id': media.id}).status_code, 403)
        student = self._headers('fam_student', 'StudentPass1!')
        created = self.url_open('/api/v1/library/reservations', headers=student, json={'media_id': media.id})
        self.assertEqual(created.status_code, 201, created.text)
        duplicate = self.url_open('/api/v1/library/reservations', headers=student, json={'media_id': media.id})
        self.assertEqual(duplicate.json()['error']['code'], 'duplicate')
        accept = self.url_open(f"/api/v1/library/reservations/{created.json()['data']['id']}/accept",
                               headers=self._headers('fam_librarian', 'LibPass1!'), method='POST')
        self.assertEqual(accept.json()['data']['state'], 'accept')

    # -- events -----------------------------------------------------------------

    def _event(self, **vals):
        start = fields.Datetime.now() + timedelta(days=3)
        return self.env['event.event'].create(dict({
            'name': 'Fam Sports Day', 'date_begin': start, 'date_end': start + timedelta(hours=4),
            'target_audience': 'specific_class', 'course_ids': [(6, 0, self.course.ids)],
        }, **vals))

    def test_event_visibility_and_registration(self):
        own = self._event()
        other = self._event(name='Other class day', course_ids=[(6, 0, self.other_course.ids)])
        events = self.url_open('/api/v1/events', headers=self._parent()).json()['data']['events']
        ids = [e['id'] for e in events]
        self.assertIn(own.id, ids)
        self.assertNotIn(other.id, ids)
        self.assertEqual(self.url_open(f'/api/v1/events/{other.id}/register', headers=self._parent(),
                                       json={'student_id': self.student.id}).status_code, 404)
        register = self.url_open(f'/api/v1/events/{own.id}/register', headers=self._parent(),
                                 json={'student_id': self.student.id})
        self.assertEqual(register.status_code, 201, register.text)
        self.assertEqual(register.json()['data']['state'], 'open')
        again = self.url_open(f'/api/v1/events/{own.id}/register', headers=self._parent(),
                              json={'student_id': self.student.id})
        self.assertEqual(again.json()['error']['code'], 'already_registered')

    def test_permission_slip_gates_confirmation(self):
        event = self._event(requires_permission_slip=True)
        reg = self.url_open(f'/api/v1/events/{event.id}/register', headers=self._parent(),
                            json={'student_id': self.student.id}).json()['data']
        self.assertEqual(reg['state'], 'draft')
        early = self.url_open(f"/api/v1/event-registrations/{reg['id']}/confirm", headers=self._parent(), method='POST')
        self.assertEqual(early.status_code, 400)
        student = self._headers('fam_student', 'StudentPass1!')
        self.assertEqual(self.url_open(f"/api/v1/event-registrations/{reg['id']}/sign-permission-slip",
                                       headers=student, json={'signed_by': 'Kid'}).status_code, 403)
        signed = self.url_open(f"/api/v1/event-registrations/{reg['id']}/sign-permission-slip",
                               headers=self._parent(), json={'signed_by': 'Fam Parent'})
        self.assertTrue(signed.json()['data']['permission_slip_signed'])
        confirmed = self.url_open(f"/api/v1/event-registrations/{reg['id']}/confirm", headers=self._parent(), method='POST')
        self.assertEqual(confirmed.json()['data']['state'], 'open')

    # -- calendar ---------------------------------------------------------------

    def test_calendar_merges_holidays_events_and_ptms(self):
        day = fields.Datetime.now().replace(hour=0, minute=0, second=0) + timedelta(days=5)
        holiday = self.env['resource.calendar.leaves'].create({
            'name': 'Fam Holiday', 'date_from': day, 'date_to': day + timedelta(hours=23)})
        event = self._event()
        ptm = self.env['bxi.ptm.meeting'].create({
            'name': 'Fam PTM', 'start_datetime': day + timedelta(hours=9), 'end_datetime': day + timedelta(hours=11),
            'venue': 'Hall', 'class_ids': [(6, 0, self.course.ids)],
        })
        holidays = self.url_open('/api/v1/calendar/holidays', headers=self._parent()).json()['data']['holidays']
        self.assertIn(holiday.id, [h['id'] for h in holidays])
        items = self.url_open(f'/api/v1/calendar?student_id={self.student.id}', headers=self._parent()).json()['data']['items']
        found = {(i['type'], i['id']) for i in items}
        self.assertTrue({('holiday', holiday.id), ('event', event.id), ('ptm', ptm.id)} <= found)
        bad = self.url_open(f'/api/v1/calendar?student_id={self.student.id}&date_from=nope', headers=self._parent())
        self.assertEqual(bad.json()['error']['code'], 'invalid_date')
        my_ptms = self.url_open('/api/v1/academic/ptm-meetings/my', headers=self._parent()).json()['data']['meetings']
        self.assertEqual([m['id'] for m in my_ptms], ptm.ids)

    # -- fees -------------------------------------------------------------------

    def test_dues_and_receipts(self):
        due_soon = self.env['op.student.fees.details'].create({
            'student_id': self.student.id, 'amount': 300.0, 'date': fields.Date.today() + timedelta(days=10)})
        overdue = self.env['op.student.fees.details'].create({
            'student_id': self.student.id, 'amount': 200.0, 'date': fields.Date.today() - timedelta(days=40)})
        dues = self.url_open(f'/api/v1/fees/students/{self.student.id}/dues', headers=self._parent()).json()['data']
        self.assertEqual(dues['total_pending'], 500.0)
        self.assertEqual(dues['overdue_amount'], 200.0)
        self.assertEqual(dues['next_due']['id'], due_soon.id)
        self.assertEqual(self.url_open(f'/api/v1/fees/students/{self.student.id}/dues',
                                       headers=self._headers('fam_other_parent', 'OtherPass1!')).status_code, 403)

        invoice = self._create_posted_invoice(self.student, 200.0, paid=200.0)
        overdue.invoice_id = invoice
        receipts = self.url_open(f'/api/v1/fees/students/{self.student.id}/receipts', headers=self._parent()).json()
        self.assertEqual(len(receipts['data']['receipts']), 1)
        self.assertEqual(receipts['data']['receipts'][0]['fee_detail_ids'], overdue.ids)
        nothing_paid = self.url_open(f'/api/v1/fees/details/{due_soon.id}/receipt', headers=self._parent())
        self.assertEqual(nothing_paid.json()['error']['code'], 'nothing_paid')

    # -- transport --------------------------------------------------------------

    def test_my_transport_card(self):
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Fam Bus Brand'})
        model = self.env['fleet.vehicle.model'].create({'name': 'Fam Bus', 'brand_id': brand.id})
        vehicle = self.env['fleet.vehicle'].create({'model_id': model.id, 'is_school_bus': True, 'seats': 30,
                                                    'license_plate': 'FAM-1'})
        fee = self.env['product.product'].create({'name': 'Fam Bus Fee', 'type': 'service',
                                                  'property_account_income_id': self.income_account.id})
        route = self.env['bxi.transport.route'].create({
            'name': 'Fam Route', 'vehicle_id': vehicle.id, 'fee_product_id': fee.id, 'fee_amount': 100.0})
        stop = self.env['bxi.transport.route.stop'].create({'route_id': route.id, 'name': 'Fam Stop', 'pickup_time': 7.5})
        route.action_activate()
        registration = self.env['bxi.transport.registration'].create({
            'student_id': self.student.id, 'route_id': route.id, 'stop_id': stop.id})
        registration.action_confirm()
        card = self.url_open(f'/api/v1/transport/my?student_id={self.student.id}', headers=self._parent()).json()
        self.assertEqual(card['data']['registrations'][0]['stop']['pickup_time'], 7.5)
        self.assertEqual(card['data']['registrations'][0]['vehicle']['license_plate'], 'FAM-1')
