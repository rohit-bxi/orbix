# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportCanteen(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.staff_user = mail_new_test_user(
            cls.env, login='canteen_api_staff',
            groups='base.group_user,bxi_school_canteen_management.group_canteen_staff',
            password='StaffPass1!')
        cls.manager_user = mail_new_test_user(
            cls.env, login='canteen_api_manager',
            groups='base.group_user,bxi_school_canteen_management.group_canteen_manager',
            password='ManagerPass1!')
        cls.student_user = mail_new_test_user(
            cls.env, login='canteen_api_student', groups='base.group_user', password='StudentPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='canteen_api_other', groups='base.group_user', password='OtherPass1!')
        cls.student = cls._create_student('CANAPI-001', user=cls.student_user)
        cls.product = cls.env['product.product'].create({
            'name': 'API Samosa', 'lst_price': 10.0, 'is_canteen_item': True, 'available_today': True,
        })

    def _student_headers(self):
        return self._headers('canteen_api_student', 'StudentPass1!')

    def test_orders_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/canteen/orders').status_code, 401)

    def test_student_can_create_own_order(self):
        resp = self.url_open('/api/v1/canteen/orders', headers=self._student_headers(), json={
            'student_id': self.student.id, 'lines': [{'product_id': self.product.id, 'quantity': 2}],
        })
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['data']['total_amount'], 20.0)
        self.assertEqual(resp.json()['data']['state'], 'draft')

    def test_other_user_cannot_order_for_student(self):
        resp = self.url_open('/api/v1/canteen/orders', headers=self._headers('canteen_api_other', 'OtherPass1!'), json={
            'student_id': self.student.id, 'lines': [{'product_id': self.product.id, 'quantity': 1}],
        })
        self.assertEqual(resp.status_code, 403)

    def test_confirm_fails_without_wallet_balance(self):
        order_id = self.url_open('/api/v1/canteen/orders', headers=self._student_headers(), json={
            'student_id': self.student.id, 'lines': [{'product_id': self.product.id, 'quantity': 1}],
        }).json()['data']['id']
        resp = self.url_open(
            f'/api/v1/canteen/orders/{order_id}/confirm', headers=self._student_headers(), method='POST')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_transition')

    def test_topup_then_confirm_full_lifecycle(self):
        student_headers = self._student_headers()
        topup = self.url_open('/api/v1/canteen/wallet/topup', headers=student_headers, json={
            'student_id': self.student.id, 'amount': 100.0, 'post_to_accounting': False,
        })
        self.assertEqual(topup.status_code, 200)
        self.assertEqual(topup.json()['data']['balance'], 100.0)

        order_id = self.url_open('/api/v1/canteen/orders', headers=student_headers, json={
            'student_id': self.student.id, 'lines': [{'product_id': self.product.id, 'quantity': 2}],
        }).json()['data']['id']

        confirm = self.url_open(f'/api/v1/canteen/orders/{order_id}/confirm', headers=student_headers, method='POST')
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.json()['data']['state'], 'confirmed')
        self.assertEqual(confirm.json()['data']['wallet_balance'], 80.0)

        staff_headers = self._headers('canteen_api_staff', 'StaffPass1!')
        preparing = self.url_open(f'/api/v1/canteen/orders/{order_id}/preparing', headers=staff_headers, method='POST')
        self.assertEqual(preparing.status_code, 200)
        ready = self.url_open(f'/api/v1/canteen/orders/{order_id}/ready', headers=staff_headers, method='POST')
        self.assertEqual(ready.status_code, 200)
        served = self.url_open(f'/api/v1/canteen/orders/{order_id}/served', headers=staff_headers, method='POST')
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.json()['data']['state'], 'served')

        cancel_after_served = self.url_open(
            f'/api/v1/canteen/orders/{order_id}/cancel', headers=staff_headers, json={}, method='POST')
        self.assertEqual(cancel_after_served.status_code, 400)

    def test_force_confirm_requires_manager(self):
        # action_force_confirm skips the balance check but still requires a
        # wallet row to exist for the patron - create one with zero balance.
        self.env['bxi.canteen.wallet'].create({'student_id': self.student.id})
        order_id = self.url_open('/api/v1/canteen/orders', headers=self._student_headers(), json={
            'student_id': self.student.id, 'lines': [{'product_id': self.product.id, 'quantity': 1}],
        }).json()['data']['id']

        staff_resp = self.url_open(
            f'/api/v1/canteen/orders/{order_id}/force-confirm',
            headers=self._headers('canteen_api_staff', 'StaffPass1!'), method='POST')
        self.assertEqual(staff_resp.status_code, 403)

        manager_resp = self.url_open(
            f'/api/v1/canteen/orders/{order_id}/force-confirm',
            headers=self._headers('canteen_api_manager', 'ManagerPass1!'), method='POST')
        self.assertEqual(manager_resp.status_code, 200)
        self.assertEqual(manager_resp.json()['data']['state'], 'confirmed')
