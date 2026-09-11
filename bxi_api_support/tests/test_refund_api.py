# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportRefund(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.refund_staff_user = mail_new_test_user(
            cls.env, login='refund_api_staff',
            groups='base.group_user,bxi_student_refund_management.group_refund_staff',
            password='RefundStaffPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='refund_api_other', groups='base.group_user', password='OtherPass1!')
        cls.student_user = mail_new_test_user(
            cls.env, login='refund_api_student', groups='base.group_user', password='StudentPass1!')
        cls.student = cls._create_student('REFAPI-001', user=cls.student_user)
        # Total fee 1000, paid 1500 => 500 excess, so a refund of up to 1500 is valid.
        cls._create_posted_invoice(cls.student, 1000.0, 1500.0)

    def _create_refund(self, amount=400.0):
        return self.url_open('/api/v1/refunds', headers=self._headers('refund_api_student', 'StudentPass1!'), json={
            'student_id': self.student.id, 'refund_type': 'fee_overpayment',
            'refund_amount': amount, 'reason': 'Overpaid this term.',
        })

    def test_refunds_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/refunds').status_code, 401)

    def test_student_can_create_own_refund(self):
        resp = self._create_refund()
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['data']['status'], 'draft')

    def test_refund_amount_exceeding_paid_rejected(self):
        resp = self._create_refund(amount=999999.0)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'validation_error')

    def test_full_lifecycle_to_completion(self):
        refund_id = self._create_refund().json()['data']['id']
        student_headers = self._headers('refund_api_student', 'StudentPass1!')
        staff_headers = self._headers('refund_api_staff', 'RefundStaffPass1!')

        submit = self.url_open(f'/api/v1/refunds/{refund_id}/submit', headers=student_headers, method='POST')
        self.assertEqual(submit.status_code, 200)

        approve_and_process = self.url_open(
            f'/api/v1/refunds/{refund_id}/approve-and-process', headers=staff_headers, method='POST')
        self.assertEqual(approve_and_process.status_code, 200)
        self.assertEqual(approve_and_process.json()['data']['status'], 'processing')

        missing_utr = self.url_open(f'/api/v1/refunds/{refund_id}/complete', headers=staff_headers, json={}, method='POST')
        self.assertEqual(missing_utr.status_code, 400)

        complete = self.url_open(
            f'/api/v1/refunds/{refund_id}/complete', headers=staff_headers, json={'refund_utr': 'UTR12345'})
        self.assertEqual(complete.status_code, 200)
        self.assertEqual(complete.json()['data']['status'], 'completed')
        self.assertTrue(complete.json()['data']['payment_id'])

    def test_non_staff_cannot_approve(self):
        refund_id = self._create_refund().json()['data']['id']
        resp = self.url_open(
            f'/api/v1/refunds/{refund_id}/approve',
            headers=self._headers('refund_api_other', 'OtherPass1!'), method='POST')
        self.assertEqual(resp.status_code, 403)

    def test_unrelated_user_cannot_view_refund(self):
        refund_id = self._create_refund().json()['data']['id']
        resp = self.url_open(
            f'/api/v1/refunds/{refund_id}', headers=self._headers('refund_api_other', 'OtherPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_get_refund_not_found(self):
        resp = self.url_open('/api/v1/refunds/999999', headers=self._headers('refund_api_staff', 'RefundStaffPass1!'))
        self.assertEqual(resp.status_code, 404)
