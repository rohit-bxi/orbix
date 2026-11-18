# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportTransport(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.staff_user = mail_new_test_user(
            cls.env, login='transport_api_staff',
            groups='base.group_user,bxi_school_transport_bus_management.group_transport_staff',
            password='StaffPass1!')
        cls.manager_user = mail_new_test_user(
            cls.env, login='transport_api_manager',
            groups='base.group_user,bxi_school_transport_bus_management.group_transport_manager',
            password='ManagerPass1!')
        cls.student_user = mail_new_test_user(
            cls.env, login='transport_api_student', groups='base.group_user', password='StudentPass1!')
        cls.student = cls._create_student('TRANAPI-001', user=cls.student_user)

        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'API Bus Brand'})
        model = cls.env['fleet.vehicle.model'].create({'name': 'API Bus Model', 'brand_id': brand.id})
        cls.fee_product = cls.env['product.product'].create({
            'name': 'API Transport Fee', 'type': 'service',
            'property_account_income_id': cls.income_account.id,
        })
        cls.vehicle = cls.env['fleet.vehicle'].create({
            'model_id': model.id, 'is_school_bus': True, 'seats': 40,
        })
        cls.route = cls.env['bxi.transport.route'].create({
            'name': 'API Route 1', 'code': 'API-RT1', 'vehicle_id': cls.vehicle.id,
            'fee_product_id': cls.fee_product.id, 'fee_amount': 500.0,
        })
        cls.stop = cls.env['bxi.transport.route.stop'].create({
            'route_id': cls.route.id, 'name': 'API Stop 1',
        })

    def _staff_headers(self):
        return self._headers('transport_api_staff', 'StaffPass1!')

    def test_routes_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/transport/routes').status_code, 401)

    def test_draft_route_hidden_from_family(self):
        resp = self.url_open('/api/v1/transport/routes', headers=self._headers('transport_api_student', 'StudentPass1!'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.route.id, [r['id'] for r in resp.json()['data']['routes']])

    def test_manager_activates_route_then_family_can_see_and_register(self):
        activate = self.url_open(
            f'/api/v1/transport/routes/{self.route.id}/activate',
            headers=self._headers('transport_api_manager', 'ManagerPass1!'), method='POST')
        self.assertEqual(activate.status_code, 200)
        self.assertEqual(activate.json()['data']['state'], 'active')

        student_headers = self._headers('transport_api_student', 'StudentPass1!')
        visible = self.url_open('/api/v1/transport/routes', headers=student_headers)
        self.assertIn(self.route.id, [r['id'] for r in visible.json()['data']['routes']])

        register = self.url_open('/api/v1/transport/registrations', headers=student_headers, json={
            'student_id': self.student.id, 'route_id': self.route.id, 'stop_id': self.stop.id,
        })
        self.assertEqual(register.status_code, 201)
        registration_id = register.json()['data']['id']
        self.assertEqual(register.json()['data']['fee_amount'], 500.0)

        confirm = self.url_open(
            f'/api/v1/transport/registrations/{registration_id}/confirm', headers=student_headers, method='POST')
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.json()['data']['state'], 'confirmed')

    def test_other_student_cannot_register_for_another_student(self):
        other_user = mail_new_test_user(
            self.env, login='transport_api_other', groups='base.group_user', password='OtherPass1!')
        self.route.action_activate()
        resp = self.url_open('/api/v1/transport/registrations', headers=self._headers('transport_api_other', 'OtherPass1!'), json={
            'student_id': self.student.id, 'route_id': self.route.id, 'stop_id': self.stop.id,
        })
        self.assertEqual(resp.status_code, 403)

    def test_bulk_register_requires_staff(self):
        batch = self.env['op.batch'].create({
            'name': 'Transport API Batch', 'code': 'TRAN-B1',
            'course_id': self.env['op.course'].create({'name': 'Transport API Course', 'code': 'TRAN-C1'}).id,
            'start_date': '2026-06-01', 'end_date': '2027-03-31',
        })
        self.route.action_activate()
        resp = self.url_open(
            '/api/v1/transport/bulk-register', headers=self._headers('transport_api_student', 'StudentPass1!'), json={
                'batch_id': batch.id, 'route_id': self.route.id, 'stop_id': self.stop.id,
            })
        self.assertEqual(resp.status_code, 403)

    def test_route_detail_archive_and_set_draft(self):
        student_headers = self._headers('transport_api_student', 'StudentPass1!')
        # A draft route is staff-only.
        self.assertEqual(self.url_open(f'/api/v1/transport/routes/{self.route.id}', headers=student_headers).status_code, 403)
        detail = self.url_open(f'/api/v1/transport/routes/{self.route.id}', headers=self._staff_headers())
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['data']['code'], 'API-RT1')
        self.assertEqual([s['id'] for s in detail.json()['data']['stops']], [self.stop.id])
        self.route.action_activate()
        self.assertEqual(self.url_open(f'/api/v1/transport/routes/{self.route.id}', headers=student_headers).status_code, 200)

        self.assertEqual(self.url_open(f'/api/v1/transport/routes/{self.route.id}/archive',
                                       headers=student_headers, method='POST').status_code, 403)
        archived = self.url_open(f'/api/v1/transport/routes/{self.route.id}/archive',
                                 headers=self._staff_headers(), method='POST')
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(archived.json()['data']['state'], 'archived')
        self.assertFalse(self.route.active)
        self.assertEqual(self.url_open(f'/api/v1/transport/routes/{self.route.id}', headers=student_headers).status_code, 403)
        self.assertNotIn(self.route.id, [r['id'] for r in self.url_open(
            '/api/v1/transport/routes', headers=student_headers).json()['data']['routes']])

        draft = self.url_open(f'/api/v1/transport/routes/{self.route.id}/set-draft',
                              headers=self._staff_headers(), method='POST')
        self.assertEqual(draft.json()['data']['state'], 'draft')
        self.assertTrue(self.route.active)
        self.assertEqual(self.url_open('/api/v1/transport/routes/999999', headers=self._staff_headers()).status_code, 404)

    def _confirmed_registration(self):
        self.route.action_activate()
        registration = self.env['bxi.transport.registration'].create({
            'student_id': self.student.id, 'route_id': self.route.id, 'stop_id': self.stop.id})
        registration.action_confirm()
        return registration

    def test_registration_detail_access(self):
        registration = self._confirmed_registration()
        url = f'/api/v1/transport/registrations/{registration.id}'
        own = self.url_open(url, headers=self._headers('transport_api_student', 'StudentPass1!'))
        self.assertEqual(own.status_code, 200, own.text)
        self.assertEqual(own.json()['data']['state'], 'confirmed')
        self.assertEqual(own.json()['data']['stop_id'], self.stop.id)
        self.assertEqual(self.url_open(url, headers=self._staff_headers()).status_code, 200)
        mail_new_test_user(self.env, login='transport_api_other2', groups='base.group_user', password='OtherPass1!')
        self.assertEqual(self.url_open(url, headers=self._headers('transport_api_other2', 'OtherPass1!')).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/transport/registrations/999999',
                                       headers=self._staff_headers()).status_code, 404)

    def test_activate_needs_paid_invoice(self):
        registration = self._confirmed_registration()
        url = f'/api/v1/transport/registrations/{registration.id}/activate'
        # Families can't activate; staff can't until the fee is paid.
        self.assertEqual(self.url_open(url, headers=self._headers('transport_api_student', 'StudentPass1!'),
                                       method='POST').status_code, 403)
        unpaid = self.url_open(url, headers=self._staff_headers(), method='POST')
        self.assertEqual(unpaid.status_code, 400)
        self.assertEqual(registration.state, 'confirmed')

        invoice = registration.invoice_id
        invoice.action_post()
        self.env['account.payment.register'].with_context(active_model='account.move', active_ids=invoice.ids).create(
            {'journal_id': self.cash_journal.id}).action_create_payments()
        paid = self.url_open(url, headers=self._staff_headers(), method='POST')
        self.assertEqual(paid.status_code, 200, paid.text)
        self.assertEqual(paid.json()['data']['state'], 'active')

    def test_family_cancels_then_staff_sets_draft(self):
        registration = self._confirmed_registration()
        invoice = registration.invoice_id
        self.assertEqual(invoice.state, 'draft')
        student_headers = self._headers('transport_api_student', 'StudentPass1!')
        cancel = self.url_open(f'/api/v1/transport/registrations/{registration.id}/cancel',
                               headers=student_headers, method='POST')
        self.assertEqual(cancel.status_code, 200, cancel.text)
        self.assertEqual(cancel.json()['data']['state'], 'cancelled')
        self.assertEqual(invoice.state, 'cancel')
        # The seat is free again.
        self.assertEqual(self.route.seats_available, self.route.capacity)

        url = f'/api/v1/transport/registrations/{registration.id}/set-draft'
        self.assertEqual(self.url_open(url, headers=student_headers, method='POST').status_code, 403)
        draft = self.url_open(url, headers=self._staff_headers(), method='POST')
        self.assertEqual(draft.status_code, 200, draft.text)
        self.assertEqual(draft.json()['data']['state'], 'draft')

    def test_registration_list_and_bulk_register(self):
        course = self.env['op.course'].create({'name': 'Transport Bulk Course', 'code': 'TRAN-C2'})
        batch = self.env['op.batch'].create({'name': 'Transport Bulk Batch', 'code': 'TRAN-B2', 'course_id': course.id,
                                             'start_date': '2026-06-01', 'end_date': '2027-03-31'})
        classmate = self._create_student('TRANAPI-002')
        self._enroll(classmate, course, batch)
        self.route.action_activate()
        bulk = self.url_open('/api/v1/transport/bulk-register', headers=self._staff_headers(), json={
            'batch_id': batch.id, 'route_id': self.route.id, 'stop_id': self.stop.id})
        self.assertEqual(bulk.status_code, 201, bulk.text)
        self.assertEqual([r['student_id'] for r in bulk.json()['data']['registrations']], [classmate.id])

        own_id = self.env['bxi.transport.registration'].create({
            'student_id': self.student.id, 'route_id': self.route.id, 'stop_id': self.stop.id}).id
        staff = self.url_open('/api/v1/transport/registrations', headers=self._staff_headers())
        self.assertEqual(staff.status_code, 200, staff.text)
        self.assertTrue({own_id} | {r['id'] for r in bulk.json()['data']['registrations']}
                        <= {r['id'] for r in staff.json()['data']['registrations']})
        mine = self.url_open('/api/v1/transport/registrations', headers=self._headers('transport_api_student', 'StudentPass1!'))
        self.assertEqual([r['id'] for r in mine.json()['data']['registrations']], [own_id])
