# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestBxiApiStepUp(HttpCase):
    """Login method on sessions and the step-up confirmation that
    sensitive routes ask of sessions opened by a weaker method."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'Step Up User', 'login': 'bxi_step_up_user', 'password': 'StepUpPass1!',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.Token = cls.env['bxi.api.token']

    def _weak_token(self):
        """A session as face login opens it: needs step-up."""
        return self.Token._issue_for_user(self.user, name='weak', step_up_required=True)

    def _record(self, raw):
        return self.Token.sudo().search([('token_hash', '=', self.Token._hash(raw))])

    def test_password_login_records_method_and_counts_as_recent(self):
        resp = self.url_open('/api/v1/auth/login', json={'login': 'bxi_step_up_user', 'password': 'StepUpPass1!'})
        data = resp.json()['data']
        self.assertEqual(data['auth_method'], 'password')
        token = self._record(data['token'])
        self.assertEqual(token.auth_method, 'password')
        self.assertFalse(token.step_up_required)
        self.assertTrue(token._is_recently_verified())

    def test_weak_session_needs_step_up_for_sensitive_route(self):
        raw = self._weak_token()
        other = self._record(self.Token._issue_for_user(self.user, name='other'))
        headers = {'Authorization': f'Bearer {raw}'}
        resp = self.url_open(f'/api/v1/auth/sessions/{other.id}/revoke', headers=headers, method='POST', json={})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['error']['code'], 'step_up_required')
        self.assertTrue(other.active)

        resp = self.url_open('/api/v1/auth/step-up', headers=headers, json={'password': 'StepUpPass1!'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['data']['verified'])

        resp = self.url_open(f'/api/v1/auth/sessions/{other.id}/revoke', headers=headers, method='POST', json={})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(other.active)

    def test_step_up_wrong_or_missing_password(self):
        headers = {'Authorization': f'Bearer {self._weak_token()}'}
        resp = self.url_open('/api/v1/auth/step-up', headers=headers, json={'password': 'nope'})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()['error']['code'], 'invalid_credentials')
        resp = self.url_open('/api/v1/auth/step-up', headers=headers, json={}, method='POST')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_credentials')

    def test_step_up_requires_auth(self):
        resp = self.url_open('/api/v1/auth/step-up', json={'password': 'StepUpPass1!'})
        self.assertEqual(resp.status_code, 401)

    def test_step_up_window_expires(self):
        raw = self._weak_token()
        token = self._record(raw)
        token._mark_verified()
        self.assertTrue(token._is_recently_verified())
        token.verified_until = fields.Datetime.now() - timedelta(seconds=1)
        self.assertFalse(token._is_recently_verified())

    def test_ttl_minutes_overrides_days(self):
        token = self._record(self.Token._issue_for_user(self.user, ttl_minutes=15))
        self.assertLess(token.expires_at, fields.Datetime.now() + timedelta(minutes=16))

    def test_sessions_list_shows_method(self):
        headers = {'Authorization': f'Bearer {self._weak_token()}'}
        resp = self.url_open('/api/v1/auth/sessions', headers=headers)
        sessions = resp.json()['data']['sessions']
        self.assertTrue(all('auth_method' in session for session in sessions))
