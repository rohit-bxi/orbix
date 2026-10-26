# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from unittest.mock import patch

from odoo.tests import HttpCase, tagged

from odoo.addons.bxi_notification_gateway.models.msg91_client import Msg91Client

CAPTURED = {}


def _fake_send_otp_sms(self, phone, otp_code):
    CAPTURED['phone'] = phone
    CAPTURED['code'] = otp_code
    return True


@tagged('post_install', '-at_install')
@patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms)
class TestBxiOtpLogin(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group_user = cls.env.ref('base.group_user')
        cls.user = cls.env['res.users'].create({
            'name': 'OTP Login User', 'login': 'otp_login_user', 'password': 'OtpLoginPass1!',
            'phone': '+91 98123-45678', 'group_ids': [(6, 0, [group_user.id])],
        })
        cls.shared_a = cls.env['res.users'].create({
            'name': 'Shared A', 'login': 'otp_shared_a', 'password': 'SharedPass1!',
            'phone': '9811100000', 'group_ids': [(6, 0, [group_user.id])],
        })
        cls.shared_b = cls.env['res.users'].create({
            'name': 'Shared B', 'login': 'otp_shared_b', 'password': 'SharedPass1!',
            'phone': '+919811100000', 'group_ids': [(6, 0, [group_user.id])],
        })

    def setUp(self):
        super().setUp()
        CAPTURED.clear()

    def _request_otp(self, phone):
        self.url_open('/api/v1/otp/request', json={'phone': phone})
        return CAPTURED['code']

    def test_otp_login_issues_token_matching_formatted_phone(self):
        code = self._request_otp('9812345678')
        resp = self.url_open('/api/v1/auth/otp-login', json={
            'phone': '9812345678', 'otp': code, 'device_name': 'OTP phone'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']
        self.assertTrue(data['token'].startswith('orb_'))
        self.assertEqual(data['user']['login'], 'otp_login_user')
        me = self.url_open('/api/v1/auth/me', headers={'Authorization': f"Bearer {data['token']}"})
        self.assertEqual(me.json()['data']['id'], self.user.id)

    def test_otp_login_wrong_code_rejected_without_revealing_account(self):
        self._request_otp('9812345678')
        resp = self.url_open('/api/v1/auth/otp-login', json={'phone': '9812345678', 'otp': '000000'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_code')

    def test_otp_login_unknown_phone_after_valid_otp(self):
        code = self._request_otp('9000000001')
        resp = self.url_open('/api/v1/auth/otp-login', json={'phone': '9000000001', 'otp': code})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error']['code'], 'no_account')

    def test_otp_login_shared_phone_refused(self):
        code = self._request_otp('9811100000')
        resp = self.url_open('/api/v1/auth/otp-login', json={'phone': '9811100000', 'otp': code})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error']['code'], 'ambiguous_phone')

    def test_forgot_password_unknown_account_still_answers_requested(self):
        resp = self.url_open('/api/v1/auth/password/forgot', json={'login': 'no_such_login'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['data']['requested'])
        self.assertNotIn('code', CAPTURED)

    def test_reset_password_by_login_full_flow_revokes_tokens(self):
        old_token = self.env['bxi.api.token']._issue_for_user(self.user)
        self.url_open('/api/v1/auth/password/forgot', json={'login': 'otp_login_user'})
        self.assertEqual(CAPTURED['phone'], '+91 98123-45678')
        resp = self.url_open('/api/v1/auth/password/reset', json={
            'login': 'otp_login_user', 'otp': CAPTURED['code'], 'new_password': 'BrandNewPass1!'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['data']['reset'])
        self.assertEqual(
            self.url_open('/api/v1/auth/me', headers={'Authorization': f'Bearer {old_token}'}).status_code, 401)
        login = self.url_open('/api/v1/auth/login', json={'login': 'otp_login_user', 'password': 'BrandNewPass1!'})
        self.assertEqual(login.status_code, 200)

    def test_login_otp_cannot_reset_password(self):
        code = self._request_otp('9812345678')
        resp = self.url_open('/api/v1/auth/password/reset', json={
            'phone': '9812345678', 'otp': code, 'new_password': 'BrandNewPass1!'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'not_found')

    def test_reset_password_missing_fields(self):
        resp = self.url_open('/api/v1/auth/password/reset', json={'login': 'otp_login_user'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_fields')
