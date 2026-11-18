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

    def _order(self, lines=True):
        payload = {'student_id': self.student.id}
        if lines:
            payload['lines'] = [{'product_id': self.shirt.id, 'quantity': 2}]
        resp = self.url_open('/api/v1/uniform/orders', headers=self._student_headers(), json=payload)
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()['data']['id']

    def _receive(self, product, quantity):
        stock = self.env['bxi.uniform.stock']._get_or_create(product.id)
        self.env['bxi.uniform.stock.move'].create({'stock_id': stock.id, 'move_type': 'receipt', 'quantity': quantity})
        return stock

    def test_load_from_policy(self):
        course, batch = self._create_class('UNIAPI')
        self._enroll(self.student, course, batch)
        self.env['bxi.uniform.policy'].create({
            'course_id': course.id, 'line_ids': [(0, 0, {'product_tmpl_id': self.shirt.product_tmpl_id.id, 'quantity': 3})]})
        order_id = self._order(lines=False)
        url = f'/api/v1/uniform/orders/{order_id}/load-from-policy'
        mail_new_test_user(self.env, login='uniform_api_stranger', groups='base.group_user', password='StrangerPass1!')
        self.assertEqual(self.url_open(url, headers=self._headers('uniform_api_stranger', 'StrangerPass1!'),
                                       method='POST').status_code, 403)
        loaded = self.url_open(url, headers=self._student_headers(), method='POST')
        self.assertEqual(loaded.status_code, 200, loaded.text)
        self.assertEqual([(l['product'], l['quantity']) for l in loaded.json()['data']['lines']],
                         [(self.shirt.display_name, 3.0)])
        self.assertEqual(loaded.json()['data']['total_amount'], 600.0)
        # Loading twice would duplicate the lines, so it's refused.
        self.assertEqual(self.url_open(url, headers=self._student_headers(), method='POST').status_code, 400)

    def test_load_from_policy_without_policy(self):
        order_id = self._order(lines=False)
        resp = self.url_open(f'/api/v1/uniform/orders/{order_id}/load-from-policy',
                             headers=self._staff_headers(), method='POST')
        self.assertEqual(resp.status_code, 400)  # the student has no class, so there's no policy to load

    def test_cancel_then_set_draft(self):
        order_id = self._order()
        self.url_open(f'/api/v1/uniform/orders/{order_id}/confirm', headers=self._student_headers(), method='POST')
        order = self.env['bxi.uniform.order'].browse(order_id)
        invoice = order.invoice_id
        self.assertEqual(invoice.state, 'draft')

        cancel = self.url_open(f'/api/v1/uniform/orders/{order_id}/cancel', headers=self._student_headers(),
                               json={'cancel_reason': 'Ordered the wrong size'})
        self.assertEqual(cancel.status_code, 200, cancel.text)
        self.assertEqual(cancel.json()['data']['state'], 'cancelled')
        self.assertEqual(order.cancel_reason, 'Ordered the wrong size')
        self.assertEqual(invoice.state, 'cancel')

        url = f'/api/v1/uniform/orders/{order_id}/set-draft'
        self.assertEqual(self.url_open(url, headers=self._student_headers(), method='POST').status_code, 403)
        draft = self.url_open(url, headers=self._staff_headers(), method='POST')
        self.assertEqual(draft.status_code, 200, draft.text)
        self.assertEqual(draft.json()['data']['state'], 'draft')
        self.assertEqual(self.url_open('/api/v1/uniform/orders/999999/cancel',
                                       headers=self._staff_headers(), method='POST').status_code, 404)

    def test_cancel_issued_order_returns_stock(self):
        stock = self._receive(self.shirt, 5)
        order_id = self._order()
        self.url_open(f'/api/v1/uniform/orders/{order_id}/confirm', headers=self._student_headers(), method='POST')
        self.url_open(f'/api/v1/uniform/orders/{order_id}/force-issue',
                      headers=self._headers('uniform_api_manager', 'ManagerPass1!'), method='POST')
        self.assertEqual(stock.quantity_on_hand, 3)
        # Body-less cancel: no reason given.
        cancel = self.url_open(f'/api/v1/uniform/orders/{order_id}/cancel', headers=self._staff_headers(), method='POST')
        self.assertEqual(cancel.status_code, 200, cancel.text)
        self.assertEqual(stock.quantity_on_hand, 5)

    def test_exchange_size(self):
        shirt_large = self.env['product.product'].create({
            'name': 'API Shirt L', 'lst_price': 250.0, 'is_uniform_item': True,
            'property_account_income_id': self.income_account.id,
        })
        small_stock = self._receive(self.shirt, 5)
        large_stock = self._receive(shirt_large, 1)
        order_id = self._order()
        self.url_open(f'/api/v1/uniform/orders/{order_id}/confirm', headers=self._student_headers(), method='POST')
        self.url_open(f'/api/v1/uniform/orders/{order_id}/force-issue',
                      headers=self._headers('uniform_api_manager', 'ManagerPass1!'), method='POST')
        order = self.env['bxi.uniform.order'].browse(order_id)
        line = order.order_line_ids
        url = f'/api/v1/uniform/orders/{order_id}/exchange'

        self.assertEqual(self.url_open(url, headers=self._student_headers(), json={
            'order_line_id': line.id, 'new_product_id': shirt_large.id}).status_code, 403)
        self.assertEqual(self.url_open(url, headers=self._staff_headers(), json={'order_line_id': line.id})
                         .json()['error']['code'], 'missing_new_product_id')
        self.assertEqual(self.url_open(url, headers=self._staff_headers(), json={
            'order_line_id': 999999, 'new_product_id': shirt_large.id}).status_code, 404)
        self.assertEqual(self.url_open(url, headers=self._staff_headers(), json={
            'order_line_id': line.id, 'new_product_id': self.shirt.id}).status_code, 400)  # same item
        # Only one large shirt in stock, two needed.
        self.assertEqual(self.url_open(url, headers=self._staff_headers(), json={
            'order_line_id': line.id, 'new_product_id': shirt_large.id}).status_code, 400)

        self._receive(shirt_large, 4)
        swapped = self.url_open(url, headers=self._staff_headers(), json={
            'order_line_id': line.id, 'new_product_id': shirt_large.id, 'note': 'Too small'})
        self.assertEqual(swapped.status_code, 200, swapped.text)
        self.assertEqual(swapped.json()['data']['lines'][0]['product'], shirt_large.display_name)
        self.assertEqual(swapped.json()['data']['total_amount'], 500.0)
        self.assertEqual(small_stock.quantity_on_hand, 5)
        self.assertEqual(large_stock.quantity_on_hand, 3)
        # The draft invoice follows the new item and price.
        self.assertEqual(order.invoice_id.invoice_line_ids.product_id, shirt_large)
        self.assertEqual(order.invoice_id.amount_untaxed, 500.0)

    def test_stock_list(self):
        self._receive(self.shirt, 7)
        resp = self.url_open('/api/v1/uniform/stock', headers=self._staff_headers())
        self.assertEqual(resp.status_code, 200, resp.text)
        rows = {r['product']: r for r in resp.json()['data']['stock']}
        self.assertEqual(rows[self.shirt.display_name]['quantity_on_hand'], 7)
        self.assertEqual(self.url_open('/api/v1/uniform/stock', headers=self._student_headers()).status_code, 403)

    def test_list_detail_and_mark_issued(self):
        stock = self._receive(self.shirt, 4)
        order_id = self._order()
        mine = self.url_open('/api/v1/uniform/orders', headers=self._student_headers())
        self.assertEqual(mine.status_code, 200, mine.text)
        self.assertEqual([o['id'] for o in mine.json()['data']['orders']], [order_id])
        detail = self.url_open(f'/api/v1/uniform/orders/{order_id}', headers=self._student_headers())
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['data']['total_amount'], 400.0)

        self.url_open(f'/api/v1/uniform/orders/{order_id}/confirm', headers=self._student_headers(), method='POST')
        invoice = self.env['bxi.uniform.order'].browse(order_id).invoice_id
        invoice.action_post()
        self.env['account.payment.register'].with_context(active_model='account.move', active_ids=invoice.ids).create(
            {'journal_id': self.cash_journal.id}).action_create_payments()
        issued = self.url_open(f'/api/v1/uniform/orders/{order_id}/mark-issued', headers=self._staff_headers(), method='POST')
        self.assertEqual(issued.status_code, 200, issued.text)
        self.assertEqual(issued.json()['data']['state'], 'issued')
        self.assertEqual(stock.quantity_on_hand, 2)
