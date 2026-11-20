# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from unittest.mock import patch

from odoo.tests import HttpCase, tagged

from odoo.addons.bxi_api.controllers import auth as auth_module


@tagged('post_install', '-at_install')
class TestBxiApiAccount(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_user = cls.env['res.users'].create({
            'name': 'API Account User',
            'login': 'bxi_api_account_user',
            'password': 'Str0ngPassw0rd!',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def _login(self, password='Str0ngPassw0rd!', device_name=None):
        resp = self.url_open('/api/v1/auth/login', json={
            'login': 'bxi_api_account_user', 'password': password, 'device_name': device_name,
        })
        return resp

    def _headers(self, token):
        return {'Authorization': f'Bearer {token}'}

    def test_me_returns_profile_fields(self):
        token = self._login().json()['data']['token']
        data = self.url_open('/api/v1/auth/me', headers=self._headers(token)).json()['data']
        self.assertEqual(data['login'], 'bxi_api_account_user')
        self.assertIn('company', data)
        self.assertFalse(data['is_admin'])

    def test_login_user_block_matches_me(self):
        body = self._login().json()['data']
        me = self.url_open('/api/v1/auth/me', headers=self._headers(body['token'])).json()['data']
        self.assertEqual(body['user'], me)

    def test_sessions_lists_only_own_active_tokens_and_flags_current(self):
        first = self._login(device_name='Phone A').json()['data']['token']
        self._login(device_name='Phone B')
        sessions = self.url_open('/api/v1/auth/sessions', headers=self._headers(first)).json()['data']['sessions']
        names = {s['name'] for s in sessions}
        self.assertTrue({'Phone A', 'Phone B'} <= names)
        current = [s for s in sessions if s['is_current']]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]['name'], 'Phone A')

    def test_revoke_session_kills_that_token(self):
        first = self._login(device_name='Phone A').json()['data']['token']
        second = self._login(device_name='Phone B').json()['data']['token']
        sessions = self.url_open('/api/v1/auth/sessions', headers=self._headers(first)).json()['data']['sessions']
        phone_b = next(s for s in sessions if s['name'] == 'Phone B')
        resp = self.url_open(
            f"/api/v1/auth/sessions/{phone_b['id']}/revoke", method='POST', headers=self._headers(first))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.url_open('/api/v1/auth/me', headers=self._headers(second)).status_code, 401)
        self.assertEqual(self.url_open('/api/v1/auth/me', headers=self._headers(first)).status_code, 200)

    def test_cannot_revoke_another_users_session(self):
        other = self.env['res.users'].create({
            'name': 'Other', 'login': 'bxi_api_account_other', 'password': 'OtherPassw0rd!',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        other_token_raw = self.env['bxi.api.token']._issue_for_user(other)
        Token = self.env['bxi.api.token'].sudo()
        other_token = Token.search([('token_hash', '=', Token._hash(other_token_raw))])
        mine = self._login().json()['data']['token']
        resp = self.url_open(
            f'/api/v1/auth/sessions/{other_token.id}/revoke', method='POST', headers=self._headers(mine))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(other_token.active)

    def test_change_password_requires_correct_old_password(self):
        token = self._login().json()['data']['token']
        resp = self.url_open('/api/v1/auth/password/change', headers=self._headers(token), json={
            'old_password': 'wrong', 'new_password': 'N3wPassw0rd!',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_old_password')

    def test_change_password_revokes_other_sessions_keeps_current(self):
        current = self._login().json()['data']['token']
        other_device = self._login().json()['data']['token']
        resp = self.url_open('/api/v1/auth/password/change', headers=self._headers(current), json={
            'old_password': 'Str0ngPassw0rd!', 'new_password': 'N3wPassw0rd!',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.url_open('/api/v1/auth/me', headers=self._headers(current)).status_code, 200)
        self.assertEqual(self.url_open('/api/v1/auth/me', headers=self._headers(other_device)).status_code, 401)
        self.assertEqual(self._login(password='N3wPassw0rd!').status_code, 200)

    def test_archived_user_token_rejected(self):
        token = self._login().json()['data']['token']
        self.test_user.active = False
        self.assertEqual(self.url_open('/api/v1/auth/me', headers=self._headers(token)).status_code, 401)


@tagged('post_install', '-at_install')
class TestBxiApiHelpers(HttpCase):
    """rate_limit is switched off for every other test (all requests come
    from 127.0.0.1), so its 429 path is exercised directly here."""

    def test_rate_limit_returns_429_after_limit(self):
        calls = []

        @auth_module.rate_limit('unit_test_bucket', limit=2)
        def route():
            calls.append(1)
            return 'ok'

        fake_request = type('R', (), {})()
        fake_request.httprequest = type('H', (), {'remote_addr': '10.9.9.9'})()
        fake_request.make_json_response = lambda body, status=200: (status, body)
        with patch.object(auth_module, 'request', fake_request), \
                patch.object(auth_module, 'RATE_LIMIT_DURING_TESTS', True):
            self.assertEqual(route(), 'ok')
            self.assertEqual(route(), 'ok')
            status, body = route()
        self.assertEqual(status, 429)
        self.assertEqual(body['error']['code'], 'rate_limited')
        self.assertEqual(len(calls), 2)

    def test_rate_limit_key_counts_each_value_apart(self):
        """With key=json_field(...), one IP's calls for different logins are
        counted apart: a classroom behind one school IP is not throttled
        together, while one login is still capped."""
        calls = []

        @auth_module.rate_limit('unit_test_keyed_bucket', limit=2, key=auth_module.json_field('login'))
        def route():
            calls.append(1)
            return 'ok'

        bodies = []
        fake_request = type('R', (), {})()
        fake_request.httprequest = type('H', (), {'remote_addr': '10.9.9.8'})()
        fake_request.make_json_response = lambda body, status=200: (status, body)
        fake_request.get_json_data = lambda: bodies[-1]
        with patch.object(auth_module, 'request', fake_request), \
                patch.object(auth_module, 'RATE_LIMIT_DURING_TESTS', True):
            for login in ('asha', 'ASHA ', 'ravi', 'meena'):
                bodies.append({'login': login})
                self.assertEqual(route(), 'ok', login)
            bodies.append({'login': 'asha'})
            status, body = route()
            self.assertEqual((status, body['error']['code']), (429, 'rate_limited'),
                             'The same login (case and spaces ignored) is capped.')
            bodies.append('not json')
            self.assertEqual(route(), 'ok', 'A malformed body is left for the route to refuse.')
        self.assertEqual(len(calls), 5)

    def test_login_is_rate_limited_per_account(self):
        """/auth/login allows 10 calls a minute per IP and login: the 11th for
        one account is refused, another account from the same IP is not."""
        users = self.env['res.users'].create([{
            'name': name, 'login': name, 'password': 'Str0ngPassw0rd!',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        } for name in ('rl_login_asha', 'rl_login_ravi')])
        auth_module._rate_buckets.clear()
        try:
            with patch.object(auth_module, 'RATE_LIMIT_DURING_TESTS', True):
                for _ in range(10):
                    resp = self.url_open('/api/v1/auth/login', json={'login': users[0].login,
                                                                     'password': 'Str0ngPassw0rd!'})
                    self.assertEqual(resp.status_code, 200, resp.text)
                resp = self.url_open('/api/v1/auth/login', json={'login': users[0].login,
                                                                 'password': 'Str0ngPassw0rd!'})
                self.assertEqual((resp.status_code, resp.json()['error']['code']), (429, 'rate_limited'))
                other = self.url_open('/api/v1/auth/login', json={'login': users[1].login,
                                                                  'password': 'Str0ngPassw0rd!'})
                self.assertEqual(other.status_code, 200, 'Another account from the same IP still signs in.')
        finally:
            auth_module._rate_buckets.clear()
