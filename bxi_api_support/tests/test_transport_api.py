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
