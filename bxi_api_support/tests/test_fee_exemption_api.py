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

    def test_reset_rejected_request_back_to_draft(self):
        req_id = self._create_request().json()['data']['id']
        staff_headers = self._headers('exemption_api_staff', 'ExemptStaffPass1!')
        student_headers = self._headers('exemption_api_student', 'StudentPass1!')
        self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}/submit', headers=student_headers, method='POST')
        # Only a rejected request can go back to draft.
        pending = self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}/reset', headers=staff_headers, method='POST')
        self.assertEqual(pending.status_code, 400)
        self.assertEqual(pending.json()['error']['code'], 'invalid_transition')
        self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}/reject', headers=staff_headers, json={
            'rejection_reason_category': 'not_eligible', 'detailed_rejection_reason': 'Income above threshold.'})
        # Only exemption staff may reset.
        self.assertEqual(self.url_open(
            f'/api/v1/fee-exemptions/requests/{req_id}/reset', headers=student_headers, method='POST').status_code, 403)
        reset = self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}/reset', headers=staff_headers, method='POST')
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(reset.json()['data']['status'], 'draft')
        self.assertFalse(reset.json()['data']['rejection_reason_category'])
        self.assertEqual(self.url_open(
            '/api/v1/fee-exemptions/requests/999999/reset', headers=staff_headers, method='POST').status_code, 404)

    def _create_exemption(self, student=None):
        return self.env['bxi.fee.exemption'].create({
            'student_id': (student or self.student).id, 'exemption_type': 'financial_hardship',
            'exemption_method': 'fixed_amount', 'fixed_amount': 250.0,
            'valid_until': fields.Date.today() + timedelta(days=60),
        })

    def test_exemption_workflow(self):
        exemption = self._create_exemption()
        staff_headers = self._headers('exemption_api_staff', 'ExemptStaffPass1!')
        base = f'/api/v1/fee-exemptions/{exemption.id}'

        submit = self.url_open(f'{base}/submit', headers=staff_headers, method='POST')
        self.assertEqual(submit.status_code, 200, submit.text)
        self.assertEqual(submit.json()['data']['approval_status'], 'pending')

        approve = self.url_open(f'{base}/approve', headers=staff_headers, method='POST')
        self.assertEqual(approve.status_code, 200, approve.text)
        data = approve.json()['data']
        self.assertEqual(data['approval_status'], 'approved')
        self.assertEqual(data['approved_by'], self.exemption_staff_user.name)
        self.assertEqual(data['approval_date'], fields.Date.today().isoformat())

        reset = self.url_open(f'{base}/reset', headers=staff_headers, method='POST')
        self.assertEqual(reset.json()['data']['approval_status'], 'draft')
        self.assertIsNone(reset.json()['data']['approved_by'])
        self.assertFalse(reset.json()['data']['approval_date'])

        self.url_open(f'{base}/submit', headers=staff_headers, method='POST')
        reject = self.url_open(f'{base}/reject', headers=staff_headers, method='POST')
        self.assertEqual(reject.status_code, 200, reject.text)
        self.assertEqual(reject.json()['data']['approval_status'], 'rejected')

    def test_exemption_transitions_staff_only(self):
        exemption = self._create_exemption()
        student_headers = self._headers('exemption_api_student', 'StudentPass1!')
        for action in ('submit', 'approve', 'reject', 'reset'):
            resp = self.url_open(f'/api/v1/fee-exemptions/{exemption.id}/{action}', headers=student_headers, method='POST')
            self.assertEqual(resp.status_code, 403, action)
        self.assertEqual(exemption.approval_status, 'draft')
        staff_headers = self._headers('exemption_api_staff', 'ExemptStaffPass1!')
        self.assertEqual(self.url_open(
            '/api/v1/fee-exemptions/999999/approve', headers=staff_headers, method='POST').status_code, 404)

    def test_list_exemptions_scoped_to_family(self):
        own = self._create_exemption()
        other = self._create_exemption(self._create_student('EXAPI-003'))
        staff = self.url_open('/api/v1/fee-exemptions', headers=self._headers('exemption_api_staff', 'ExemptStaffPass1!'))
        self.assertEqual(staff.status_code, 200, staff.text)
        self.assertTrue({own.id, other.id} <= {e['id'] for e in staff.json()['data']['exemptions']})

        mine = self.url_open('/api/v1/fee-exemptions', headers=self._headers('exemption_api_student', 'StudentPass1!')).json()
        self.assertEqual([e['id'] for e in mine['data']['exemptions']], [own.id])
        self.assertEqual(mine['meta']['total'], 1)

        unrelated = self.url_open('/api/v1/fee-exemptions', headers=self._headers('exemption_api_other', 'OtherPass1!')).json()
        self.assertEqual(unrelated['data']['exemptions'], [])

    def test_request_list_detail_and_exemption_detail(self):
        req_id = self._create_request().json()['data']['id']
        student_headers = self._headers('exemption_api_student', 'StudentPass1!')
        mine = self.url_open('/api/v1/fee-exemptions/requests', headers=student_headers)
        self.assertEqual(mine.status_code, 200, mine.text)
        self.assertEqual([r['id'] for r in mine.json()['data']['requests']], [req_id])
        self.assertEqual(self.url_open('/api/v1/fee-exemptions/requests', headers=self._headers(
            'exemption_api_other', 'OtherPass1!')).json()['data']['requests'], [])
        detail = self.url_open(f'/api/v1/fee-exemptions/requests/{req_id}', headers=student_headers)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['data']['requested_amount'], 300.0)

        exemption = self._create_exemption()
        own = self.url_open(f'/api/v1/fee-exemptions/{exemption.id}', headers=student_headers)
        self.assertEqual(own.status_code, 200, own.text)
        self.assertEqual((own.json()['data']['fixed_amount'], own.json()['data']['approval_status']), (250.0, 'draft'))
        self.assertEqual(self.url_open(f'/api/v1/fee-exemptions/{exemption.id}', headers=self._headers(
            'exemption_api_other', 'OtherPass1!')).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/fee-exemptions/999999', headers=student_headers).status_code, 404)
