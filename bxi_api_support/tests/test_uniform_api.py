# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportUniform(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.staff_user = mail_new_test_user(
            cls.env, login='uniform_api_staff',
            groups='base.group_user,bxi_uniform_management.group_uniform_staff',
            password='StaffPass1!')
        cls.manager_user = mail_new_test_user(
            cls.env, login='uniform_api_manager',
            groups='base.group_user,bxi_uniform_management.group_uniform_manager',
            password='ManagerPass1!')
        cls.student_user = mail_new_test_user(
            cls.env, login='uniform_api_student', groups='base.group_user', password='StudentPass1!')
        cls.student = cls._create_student('UNIAPI-001', user=cls.student_user)
        cls.shirt = cls.env['product.product'].create({
            'name': 'API Shirt', 'lst_price': 200.0, 'is_uniform_item': True,
            'property_account_income_id': cls.income_account.id,
        })

    def _student_headers(self):
        return self._headers('uniform_api_student', 'StudentPass1!')

    def _staff_headers(self):
        return self._headers('uniform_api_staff', 'StaffPass1!')

    def test_orders_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/uniform/orders').status_code, 401)

    def test_student_creates_order_staff_confirms_and_force_issues(self):
        create = self.url_open('/api/v1/uniform/orders', headers=self._student_headers(), json={
            'student_id': self.student.id, 'lines': [{'product_id': self.shirt.id, 'quantity': 2}],
        })
        self.assertEqual(create.status_code, 201)
        order_id = create.json()['data']['id']
        self.assertEqual(create.json()['data']['total_amount'], 400.0)

        staff_headers = self._staff_headers()
        confirm = self.url_open(f'/api/v1/uniform/orders/{order_id}/confirm', headers=staff_headers, method='POST')
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.json()['data']['state'], 'confirmed')

        mark_issued_before_payment = self.url_open(
            f'/api/v1/uniform/orders/{order_id}/mark-issued', headers=staff_headers, method='POST')
        self.assertEqual(mark_issued_before_payment.status_code, 400)

        force_issue_staff = self.url_open(
            f'/api/v1/uniform/orders/{order_id}/force-issue', headers=staff_headers, method='POST')
        self.assertEqual(force_issue_staff.status_code, 403)

        force_issue_manager = self.url_open(
            f'/api/v1/uniform/orders/{order_id}/force-issue',
            headers=self._headers('uniform_api_manager', 'ManagerPass1!'), method='POST')
        self.assertEqual(force_issue_manager.status_code, 200)
        self.assertEqual(force_issue_manager.json()['data']['state'], 'issued')

    def test_other_student_cannot_view_order(self):
        create = self.url_open('/api/v1/uniform/orders', headers=self._student_headers(), json={
            'student_id': self.student.id, 'lines': [{'product_id': self.shirt.id, 'quantity': 1}],
        })
        order_id = create.json()['data']['id']

        other_student_user = mail_new_test_user(
            self.env, login='uniform_api_other_student', groups='base.group_user', password='OtherPass1!')
        self._create_student('UNIAPI-002', user=other_student_user)

        resp = self.url_open(
            f'/api/v1/uniform/orders/{order_id}', headers=self._headers('uniform_api_other_student', 'OtherPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_missing_patron_rejected(self):
        resp = self.url_open('/api/v1/uniform/orders', headers=self._staff_headers(), json={
            'lines': [{'product_id': self.shirt.id, 'quantity': 1}],
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_patron')
