# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Codes sent by email while SMS is not set up (the "auto" default), and
the delivery setting's other modes."""
import re
from unittest.mock import patch

from odoo.tests import HttpCase, tagged

from odoo.addons.bxi_notification_gateway.models.msg91_client import Msg91Client

SMS = []


def _fake_send_otp_sms(self, phone, otp_code):
    SMS.append({'phone': phone, 'code': otp_code})
    return True


@tagged('post_install', '-at_install')
@patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms)
class TestBxiOtpDelivery(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.email = 'office@delivery-school.test'
        group_user = cls.env.ref('base.group_user')
        cls.user = cls.env['res.users'].create({
            'name': 'Delivery User', 'login': 'otp_delivery_user', 'password': 'DeliveryPass1!',
            'phone': '+91 97001-23456', 'email': 'delivery.user@example.com',
            'group_ids': [(6, 0, [group_user.id])],
        })
        cls.no_phone = cls.env['res.users'].create({
            'name': 'Email Only User', 'login': 'otp_email_only', 'password': 'EmailOnlyPass1!',
            'email': 'email.only@example.com', 'group_ids': [(6, 0, [group_user.id])],
        })
        cls.no_contact = cls.env['res.users'].create({
            'name': 'No Contact User', 'login': 'otp_no_contact', 'password': 'NoContactPass1!',
            'group_ids': [(6, 0, [group_user.id])],
        })

    def setUp(self):
        super().setUp()
        SMS.clear()
        self.mails = []
        mails_out = self.mails

        def fake_send(mails, *args, **kwargs):
            for mail in mails:
                mails_out.append({'to': mail.email_to, 'subject': mail.subject, 'body': str(mail.body_html)})
            mails.write({'state': 'sent'})
            return True

        patcher = patch.object(type(self.env['mail.mail']), '_send', fake_send)
        patcher.start()
        self.addCleanup(patcher.stop)
        ICP = self.env['ir.config_parameter'].sudo()
        for key in ('otp_delivery', 'msg91_auth_key', 'msg91_otp_template_id', 'msg91_credentials_template_id'):
            ICP.set_param('bxi_notification_gateway.%s' % key, False)

    def _set(self, **params):
        for key, value in params.items():
            self.env['ir.config_parameter'].sudo().set_param('bxi_notification_gateway.%s' % key, value)

    def _msg91_ready(self):
        self._set(msg91_auth_key='key', msg91_otp_template_id='tmpl')

    def _code(self):
        return re.search(r'(\d{6})', self.mails[-1]['body']).group(1)

    # -- the setting ---------------------------------------------------------------

    def test_channels_per_mode(self):
        Otp = self.env['bxi.otp.request']
        self.assertEqual(Otp._delivery_channels(), ('email',), 'Auto without MSG91 is email.')
        self._msg91_ready()
        self.assertEqual(Otp._delivery_channels(), ('sms',), 'Auto with MSG91 is SMS.')
        self.assertEqual(Otp._delivery_channels('credentials'), ('email',),
                         'New logins need their own SMS template.')
        self._set(otp_delivery='both')
        self.assertEqual(Otp._delivery_channels(), ('sms', 'email'))
        self._set(otp_delivery='email')
        self.assertEqual(Otp._delivery_channels(), ('email',))
        self._set(otp_delivery='both', msg91_auth_key=False)
        self.assertEqual(Otp._delivery_channels(), ('email',), '"Both" without MSG91 is email.')

    # -- phone login ---------------------------------------------------------------

    def test_phone_login_by_email(self):
        resp = self.url_open('/api/v1/otp/request', json={'phone': '9700123456'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data'], {'sent': True, 'channel': 'email'})
        self.assertFalse(SMS)
        self.assertEqual(self.mails[-1]['to'], 'delivery.user@example.com')
        self.assertIn('login code', self.mails[-1]['subject'])
        resp = self.url_open('/api/v1/auth/otp-login', json={'phone': '9700123456', 'otp': self._code()})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['user']['login'], 'otp_delivery_user')

    def test_unregistered_phone_answers_the_same(self):
        resp = self.url_open('/api/v1/otp/request', json={'phone': '9000000077'})
        self.assertEqual(resp.json()['data'], {'sent': True, 'channel': 'email'})
        self.assertFalse(self.mails)
        self.assertFalse(self.env['bxi.otp.request'].sudo().search_count([('phone', '=', '9000000077')]))

    def test_phone_request_is_throttled_but_last_code_works(self):
        self.url_open('/api/v1/otp/request', json={'phone': '9700123456'})
        first = self._code()
        self.url_open('/api/v1/otp/request', json={'phone': '9700123456'})
        self.assertEqual(len(self.mails), 1, 'A second code within a minute is not emailed.')
        resp = self.url_open('/api/v1/auth/otp-login', json={'phone': '9700123456', 'otp': first})
        self.assertEqual(resp.status_code, 200)

    def test_auto_with_msg91_texts(self):
        self._msg91_ready()
        resp = self.url_open('/api/v1/otp/request', json={'phone': '9700123456'})
        self.assertEqual(resp.json()['data'], {'sent': True, 'channel': 'sms'})
        self.assertEqual(len(SMS), 1)
        self.assertFalse(self.mails)

    def test_both_sends_one_code_twice(self):
        self._msg91_ready()
        self._set(otp_delivery='both')
        resp = self.url_open('/api/v1/otp/request', json={'phone': '9700123456'})
        self.assertEqual(resp.json()['data']['channel'], 'both')
        self.assertEqual(SMS[-1]['code'], self._code())

    # -- password reset ------------------------------------------------------------

    def test_reset_by_login_without_phone(self):
        old = self.env['bxi.api.token']._issue_for_user(self.no_phone)
        resp = self.url_open('/api/v1/auth/password/forgot', json={'login': 'otp_email_only'})
        self.assertEqual(resp.json()['data'], {'requested': True, 'channel': 'email'})
        self.assertEqual(self.mails[-1]['to'], 'email.only@example.com')
        self.assertIn('password reset code', self.mails[-1]['subject'])
        resp = self.url_open('/api/v1/auth/password/reset', json={
            'login': 'otp_email_only', 'otp': self._code(), 'new_password': 'FreshEmailPass1!'})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(self.url_open('/api/v1/auth/me', headers={'Authorization': f'Bearer {old}'}).status_code, 401)
        login = self.url_open('/api/v1/auth/login', json={'login': 'otp_email_only', 'password': 'FreshEmailPass1!'})
        self.assertEqual(login.status_code, 200)

    def test_reset_by_phone_with_emailed_code(self):
        self.url_open('/api/v1/auth/password/forgot', json={'phone': '9700123456'})
        resp = self.url_open('/api/v1/auth/password/reset', json={
            'phone': '9700123456', 'otp': self._code(), 'new_password': 'PhoneResetPass1!'})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_reset_code_is_for_its_own_account(self):
        self.url_open('/api/v1/auth/password/forgot', json={'login': 'otp_email_only'})
        resp = self.url_open('/api/v1/auth/password/reset', json={
            'login': 'otp_delivery_user', 'otp': self._code(), 'new_password': 'NotMinePass1!'})
        self.assertEqual(resp.status_code, 400)

    def test_login_code_cannot_reset(self):
        self.url_open('/api/v1/otp/request', json={'phone': '9700123456'})
        resp = self.url_open('/api/v1/auth/password/reset', json={
            'login': 'otp_delivery_user', 'otp': self._code(), 'new_password': 'NotAllowedPass1!'})
        self.assertEqual(resp.json()['error']['code'], 'not_found')

    def test_forgot_for_account_without_contact_still_answers_requested(self):
        resp = self.url_open('/api/v1/auth/password/forgot', json={'login': 'otp_no_contact'})
        self.assertTrue(resp.json()['data']['requested'])
        self.assertFalse(self.mails)

    # -- step-up -------------------------------------------------------------------

    def test_step_up_by_email(self):
        raw = self.env['bxi.api.token']._issue_for_user(self.no_phone, step_up_required=True)
        headers = {'Authorization': f'Bearer {raw}'}
        resp = self.url_open('/api/v1/auth/step-up/otp-request', headers=headers, json={}, method='POST')
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertEqual((data['channel'], data['email_hint'], data['phone_hint']),
                         ('email', 'em****@example.com', None))
        self.assertIn('verification code', self.mails[-1]['subject'])
        resp = self.url_open('/api/v1/auth/step-up/otp-request', headers=headers, json={}, method='POST')
        self.assertEqual((resp.status_code, resp.json()['error']['code']), (429, 'otp_throttled'))
        resp = self.url_open('/api/v1/auth/step-up', headers=headers, json={'otp': self._code()})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_step_up_needs_an_email(self):
        raw = self.env['bxi.api.token']._issue_for_user(self.no_contact, step_up_required=True)
        resp = self.url_open('/api/v1/auth/step-up/otp-request', headers={'Authorization': f'Bearer {raw}'},
                             json={}, method='POST')
        self.assertEqual((resp.status_code, resp.json()['error']['code']), (400, 'no_email'))

    def test_step_up_sms_mode_still_needs_a_phone(self):
        self._set(otp_delivery='sms')
        raw = self.env['bxi.api.token']._issue_for_user(self.no_phone, step_up_required=True)
        resp = self.url_open('/api/v1/auth/step-up/otp-request', headers={'Authorization': f'Bearer {raw}'},
                             json={}, method='POST')
        self.assertEqual(resp.json()['error']['code'], 'no_phone')
