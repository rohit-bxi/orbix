# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestBxiApiTemporaryPassword(HttpCase):
    """One-time passwords set by the school office: they sign in, but the
    session can only change the password until the person picks their own;
    an expired one no longer signs in."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'Temp Password User', 'login': 'bxi_temp_pw_user', 'password': 'OriginalPass1!',
            'group_ids': [(6, 0, [cls.env.ref('base.group_portal').id])],
        })

    def _login(self, password):
        return self.url_open('/api/v1/auth/login', json={'login': 'bxi_temp_pw_user', 'password': password})

    def test_one_time_password_flow(self):
        old_token = self._login('OriginalPass1!').json()['data']['token']
        otp = self.user._bxi_set_temporary_password()
        self.assertEqual(len(otp), 10)
        self.assertTrue(self.user.bxi_must_change_password)
        self.assertTrue(self.user.bxi_temp_password_expires_at)
        self.assertEqual(self.url_open('/api/v1/auth/me', headers={'Authorization': f'Bearer {old_token}'}).status_code,
                         401, 'Setting a one-time password signs the account out everywhere.')
        self.assertEqual(self._login('OriginalPass1!').status_code, 401)

        login = self._login(otp)
        self.assertEqual(login.status_code, 200, login.text)
        self.assertTrue(login.json()['data']['user']['must_change_password'])
        headers = {'Authorization': f"Bearer {login.json()['data']['token']}"}
        blocked = self.url_open('/api/v1/auth/sessions', headers=headers)
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()['error']['code'], 'password_change_required')
        self.assertEqual(self.url_open('/api/v1/auth/me', headers=headers).status_code, 200)

        same = self.url_open('/api/v1/auth/password/change', headers=headers,
                             json={'old_password': otp, 'new_password': otp})
        self.assertEqual(same.json()['error']['code'], 'same_password')
        short = self.url_open('/api/v1/auth/password/change', headers=headers,
                              json={'old_password': otp, 'new_password': 'short'})
        self.assertEqual(short.json()['error']['code'], 'invalid_password')
        changed = self.url_open('/api/v1/auth/password/change', headers=headers,
                                json={'old_password': otp, 'new_password': 'MyOwnPass99!'})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertFalse(self.user.bxi_must_change_password)
        self.assertFalse(self.user.bxi_temp_password_expires_at)
        self.assertEqual(self.url_open('/api/v1/auth/sessions', headers=headers).status_code, 200)

    def test_typed_password_is_one_time_too(self):
        self.assertEqual(self.user._bxi_set_temporary_password('OfficeTyped1'), 'OfficeTyped1')
        self.assertTrue(self._login('OfficeTyped1').json()['data']['user']['must_change_password'])

    def test_expired_one_time_password_is_refused(self):
        otp = self.user._bxi_set_temporary_password()
        self.user.sudo().bxi_temp_password_expires_at = fields.Datetime.now() - timedelta(minutes=1)
        self.assertEqual(self._login(otp).status_code, 401)

    def test_admin_password_write_clears_the_flag(self):
        self.user._bxi_set_temporary_password()
        self.user.sudo().write({'password': 'AdminChosen1!'})
        self.assertFalse(self.user.bxi_must_change_password)
        self.assertFalse(self._login('AdminChosen1!').json()['data']['user']['must_change_password'])
