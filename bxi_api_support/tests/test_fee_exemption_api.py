# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportFeeExemption(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.exemption_staff_user = mail_new_test_user(
            cls.env, login='exemption_api_staff',
            groups='base.group_user,bxi_fee_exemption_management.group_exemption_staff',
            password='ExemptStaffPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='exemption_api_other', groups='base.group_user', password='OtherPass1!')
        cls.student_user = mail_new_test_user(
            cls.env, login='exemption_api_student', groups='base.group_user', password='StudentPass1!')
        cls.student = cls._create_student('EXAPI-001', user=cls.student_user)
        cls._create_posted_invoice(cls.student, 2000.0, 1500.0)

    def _create_request(self, login='exemption_api_student', password='StudentPass1!'):
        return self.url_open('/api/v1/fee-exemptions/requests', headers=self._headers(login, password), json={
            'student_id': self.student.id, 'exemption_type': 'financial_hardship',
            'request_value_type': 'amount', 'requested_amount': 300.0,
            'reason': 'Family financial hardship this term.',
        })

    def test_requests_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/fee-exemptions/requests').status_code, 401)

    def test_student_can_create_own_request(self):
        resp = self._create_request()
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['data']['status'], 'draft')

    def test_cannot_create_request_for_unrelated_student(self):
        other_student = self._create_student('EXAPI-002')
        resp = self.url_open('/api/v1/fee-exemptions/requests', headers=self._headers('exemption_api_other', 'OtherPass1!'), json={
            'student_id': other_student.id, 'exemption_type': 'financial_hardship',
            'requested_amount': 100.0, 'reason': 'n/a',
        })
        self.assertEqual(resp.status_code, 403)

    def test_create_request_missing_reason_rejected(self):
        resp = self.url_open('/api/v1/fee-exemptions/requests', headers=self._headers('exemption_api_student', 'StudentPass1!'), json={
            'student_id': self.student.id, 'exemption_type': 'financial_hardship', 'requested_amount': 100.0,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_reason')

    def test_submit_then_staff_start_review_and_approve(self):
        req_id = self._create_request().json()['data']['id']
        student_headers = self._headers('exemption_api_student', 'StudentPass1!')
        staff_headers = self._headers('exemption_api_staff', 'ExemptStaffPass1!')

        submit = self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}/submit', headers=student_headers, method='POST')
        self.assertEqual(submit.status_code, 200)
        self.assertEqual(submit.json()['data']['status'], 'pending_review')

        review = self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}/start-review', headers=staff_headers, method='POST')
        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json()['data']['status'], 'under_review')

        approve = self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}/approve', headers=staff_headers, json={
            'approved_amount': 300.0,
            'valid_until': (fields.Date.today() + timedelta(days=90)).isoformat(),
        })
        self.assertEqual(approve.status_code, 200)
        self.assertEqual(approve.json()['data']['status'], 'approved')
        self.assertTrue(approve.json()['data']['exemption_id'])

    def test_approve_missing_approved_amount_rejected(self):
        req_id = self._create_request().json()['data']['id']
        staff_headers = self._headers('exemption_api_staff', 'ExemptStaffPass1!')
        self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}/submit', headers=self._headers('exemption_api_student', 'StudentPass1!'), method='POST')
        self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}/start-review', headers=staff_headers, method='POST')

        resp = self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}/approve', headers=staff_headers, json={
            'valid_until': (fields.Date.today() + timedelta(days=90)).isoformat(),
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_approved_amount')

    def test_approve_out_of_order_rejected(self):
        req_id = self._create_request().json()['data']['id']
        staff_headers = self._headers('exemption_api_staff', 'ExemptStaffPass1!')
        resp = self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}/approve', headers=staff_headers, json={
            'approved_amount': 300.0, 'valid_until': (fields.Date.today() + timedelta(days=90)).isoformat(),
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_transition')

    def test_reject_request(self):
        req_id = self._create_request().json()['data']['id']
        staff_headers = self._headers('exemption_api_staff', 'ExemptStaffPass1!')
        self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}/submit', headers=self._headers('exemption_api_student', 'StudentPass1!'), method='POST')

        resp = self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}/reject', headers=staff_headers, json={
            'rejection_reason_category': 'not_eligible',
            'detailed_rejection_reason': 'Does not meet income threshold.',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['status'], 'rejected')

    def test_non_staff_cannot_approve(self):
        req_id = self._create_request().json()['data']['id']
        resp = self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}/approve', headers=self._headers('exemption_api_other', 'OtherPass1!'), json={
            'approved_amount': 300.0, 'valid_until': fields.Date.today().isoformat(),
        })
        self.assertEqual(resp.status_code, 403)

    def test_unrelated_user_cannot_view_request(self):
        req_id = self._create_request().json()['data']['id']
        resp = self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}', headers=self._headers('exemption_api_other', 'OtherPass1!'))
        self.assertEqual(resp.status_code, 403)
