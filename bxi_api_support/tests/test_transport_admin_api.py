# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportTransportAdmin(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.staff_user = mail_new_test_user(
            cls.env, login='tadm_staff', password='StaffPass1!',
            groups='base.group_user,bxi_school_transport_bus_management.group_transport_staff')
        cls.teacher_user = mail_new_test_user(
            cls.env, login='tadm_teacher', password='TeacherPass1!', groups='base.group_user')
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'Tadm Brand'})
        cls.model = cls.env['fleet.vehicle.model'].create({'name': 'Tadm Bus', 'brand_id': brand.id})
        cls.fee_product = cls.env['product.product'].create({'name': 'Tadm Transport Fee', 'type': 'service'})

    def _staff(self):
        return self._headers('tadm_staff', 'StaffPass1!')

    def _post(self, path, payload, headers=None):
        return self.url_open(path, headers=headers or self._staff(), json=payload, method='POST')

    def _driver(self, **extra):
        return self._post('/api/v1/transport/drivers', dict({
            'name': 'Tadm Driver', 'phone': '9000000009', 'license_number': 'DL-TADM-1', 'license_type': 'hmv',
            'license_expiry': '2030-01-31'}, **extra))

    def _vehicle(self, **extra):
        return self._post('/api/v1/transport/vehicles', dict({
            'model_id': self.model.id, 'license_plate': 'TADM-01', 'seats': 30}, **extra))

    def test_access(self):
        teacher = self._headers('tadm_teacher', 'TeacherPass1!')
        for path in ('/api/v1/transport/routes', '/api/v1/transport/vehicles', '/api/v1/transport/drivers'):
            self.assertEqual(self._post(path, {}, teacher).status_code, 403, path)

    def test_driver_vehicle_route(self):
        driver = self._driver()
        self.assertEqual(driver.status_code, 201, driver.text)
        driver = driver.json()['data']
        self.assertEqual(driver['phone'], '9000000009')
        self.assertEqual(self._driver(license_type='car').json()['error']['code'], 'invalid_license_type')

        vehicle = self._vehicle(driver_id=driver['id'], attendant={'name': 'Tadm Helper', 'phone': '9000000010'})
        self.assertEqual(vehicle.status_code, 201, vehicle.text)
        vehicle = vehicle.json()['data']
        self.assertEqual(vehicle['driver']['id'], driver['id'])
        self.assertEqual(vehicle['attendant']['name'], 'Tadm Helper')
        self.assertEqual(self._vehicle().json()['error']['code'], 'duplicate_license_plate')

        route = self._post('/api/v1/transport/routes', {
            'name': 'Tadm North', 'code': 'TADM-N', 'vehicle_id': vehicle['id'], 'fee_product_id': self.fee_product.id,
            'fee_amount': 800, 'stops': [{'name': 'Gate'}, {'name': 'Market', 'pickup_time': 7.5}]})
        self.assertEqual(route.status_code, 201, route.text)
        route = route.json()['data']
        self.assertEqual(route['state'], 'draft')
        self.assertEqual([s['name'] for s in route['stops']], ['Gate', 'Market'])
        self.assertEqual(route['seats_available'], 30)

        updated = self._post(f"/api/v1/transport/routes/{route['id']}/update", {'distance_km': 12.5, 'name': 'Tadm N1'})
        self.assertEqual(updated.json()['data']['distance_km'], 12.5)
        self.assertEqual(self._post('/api/v1/transport/routes', {
            'name': 'Dup', 'code': 'TADM-N', 'vehicle_id': vehicle['id'], 'fee_product_id': self.fee_product.id,
        }).json()['error']['code'], 'duplicate_code')

        seats = self._post(f"/api/v1/transport/vehicles/{vehicle['id']}/update", {'seats': 35, 'attendant': None})
        self.assertEqual(seats.json()['data']['seats'], 35)
        self.assertIsNone(seats.json()['data']['attendant'])
        renamed = self._post(f"/api/v1/transport/drivers/{driver['id']}/update",
                             {'name': 'Tadm Driver Two', 'status': 'on_leave'})
        self.assertEqual(renamed.json()['data']['name'], 'Tadm Driver Two')
        self.assertEqual(renamed.json()['data']['status'], 'on_leave')

    def test_non_bus_vehicle_refused(self):
        car = self.env['fleet.vehicle'].create({'model_id': self.model.id, 'license_plate': 'TADM-CAR'})
        resp = self._post('/api/v1/transport/routes', {'name': 'X', 'vehicle_id': car.id,
                                                       'fee_product_id': self.fee_product.id})
        self.assertEqual(resp.json()['error']['code'], 'not_school_bus')
        self.assertEqual(self._post(f'/api/v1/transport/vehicles/{car.id}/update', {'seats': 4}).status_code, 404)

    def test_vehicle_models_master(self):
        items = self.url_open('/api/v1/masters/vehicle-models', headers=self._staff()).json()['data']['items']
        self.assertIn(self.model.id, [m['id'] for m in items])
