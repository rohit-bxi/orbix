# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Two-factor authentication: set-up, enable, the two-step login and
disable, on Odoo's auth_totp."""
import base64
import time

from odoo.tests import HttpCase, tagged

from odoo.addons.auth_totp.models.totp import TIMESTEP, hotp


@tagged('post_install', '-at_install')
class TestBxiApiTwoFactor(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'Two Factor User', 'login': 'bxi_2fa_user', 'password': 'TwoFactorPass1!',
            'group_ids': [(6, 0, [cls.env.ref('base.group_portal').id])],
        })

    def _login(self):
        return self.url_open('/api/v1/auth/login', json={'login': 'bxi_2fa_user', 'password': 'TwoFactorPass1!'}, method='POST')

    def _code(self, secret, step=0):
        key = base64.b32decode(secret.replace(' ', '').upper())
        return '%06d' % hotp(key, int(time.time() / TIMESTEP) + step)

    def test_full_flow(self):
        token = self._login().json()['data']['token']
        headers = {'Authorization': 'Bearer %s' % token}
        self.assertFalse(self.url_open('/api/v1/auth/2fa', headers=headers).json()['data']['enabled'])
        self.assertFalse(self.url_open('/api/v1/auth/me', headers=headers).json()['data']['two_factor_enabled'])

        setup = self.url_open('/api/v1/auth/2fa/setup', headers=headers, json={}, method='POST').json()['data']
        self.assertTrue(setup['otpauth_url'].startswith('otpauth://totp/'))
        self.assertTrue(setup['qr_code_png_base64'])
        secret = setup['secret']

        wrong = self.url_open('/api/v1/auth/2fa/enable', headers=headers,
                              json={'setup_id': setup['setup_id'], 'code': '000000'}, method='POST')
        self.assertEqual(wrong.status_code, 400)
        enabled = self.url_open('/api/v1/auth/2fa/enable', headers=headers,
                                json={'setup_id': setup['setup_id'], 'code': self._code(secret, -1)}, method='POST')
        self.assertEqual(enabled.status_code, 200, enabled.text)
        self.assertTrue(self.user.totp_enabled)

        # Password alone no longer hands out a token.
        first = self._login().json()['data']
        self.assertTrue(first['mfa_required'])
        self.assertNotIn('token', first)
        bad = self.url_open('/api/v1/auth/login/2fa', json={'mfa_token': first['mfa_token'], 'code': '123456'}, method='POST')
        self.assertEqual(bad.status_code, 401)
        forged = self.url_open('/api/v1/auth/login/2fa',
                               json={'mfa_token': first['mfa_token'][:-2] + 'xx', 'code': self._code(secret)}, method='POST')
        self.assertEqual(forged.json()['error']['code'], 'mfa_token_expired')
        second = self.url_open('/api/v1/auth/login/2fa', json={'mfa_token': first['mfa_token'],
                                                               'code': self._code(secret), 'device_name': 'Phone'}, method='POST')
        self.assertEqual(second.status_code, 200, second.text)
        new_token = second.json()['data']['token']
        self.assertEqual(second.json()['data']['user']['id'], self.user.id)

        # The code just used can't be used again.
        replay = self.url_open('/api/v1/auth/login/2fa', json={'mfa_token': self._login().json()['data']['mfa_token'],
                                                               'code': self._code(secret)}, method='POST')
        self.assertEqual(replay.status_code, 401)

        new_headers = {'Authorization': 'Bearer %s' % new_token}
        off = self.url_open('/api/v1/auth/2fa/disable', headers=new_headers, json={'code': self._code(secret, 1)}, method='POST')
        self.assertEqual(off.status_code, 200, off.text)
        self.assertFalse(self.user.totp_enabled)
        self.assertIn('token', self._login().json()['data'])

    def test_setup_needs_recent_password(self):
        weak = self.env['bxi.api.token']._issue_for_user(self.user, name='face', step_up_required=True)
        resp = self.url_open('/api/v1/auth/2fa/setup', headers={'Authorization': 'Bearer %s' % weak}, json={}, method='POST')
        self.assertEqual(resp.json()['error']['code'], 'step_up_required')

    def test_login_2fa_requires_fields(self):
        resp = self.url_open('/api/v1/auth/login/2fa', json={'mfa_token': 'x'}, method='POST')
        self.assertEqual(resp.json()['error']['code'], 'missing_credentials')
