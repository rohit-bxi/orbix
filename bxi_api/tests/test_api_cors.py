# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

PORTAL = 'https://portal.example.com'


@tagged('post_install', '-at_install')
class TestBxiApiCors(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.users'].create({
            'name': 'API CORS User',
            'login': 'bxi_api_cors_user',
            'password': 'Str0ngPassw0rd!',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def _preflight(self, url, origin=PORTAL):
        return self.url_open(url, method='OPTIONS', headers={
            'Origin': origin,
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'authorization,content-type',
        })

    def _login(self, origin=PORTAL):
        return self.url_open('/api/v1/auth/login', headers={'Origin': origin}, json={
            'login': 'bxi_api_cors_user', 'password': 'Str0ngPassw0rd!',
        })

    def test_login_preflight_is_answered(self):
        resp = self._preflight('/api/v1/auth/login')
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.headers['Access-Control-Allow-Origin'], '*')
        self.assertIn('POST', resp.headers['Access-Control-Allow-Methods'])
        allowed_headers = resp.headers['Access-Control-Allow-Headers'].lower()
        self.assertIn('authorization', allowed_headers)
        self.assertIn('content-type', allowed_headers)

    def test_preflight_skips_require_auth(self):
        resp = self._preflight('/api/v1/auth/me')
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.headers['Access-Control-Allow-Origin'], '*')

    def test_actual_and_error_responses_carry_origin(self):
        resp = self._login()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['Access-Control-Allow-Origin'], '*')
        self.assertIn('Content-Disposition', resp.headers['Access-Control-Expose-Headers'])
        unauthorized = self.url_open('/api/v1/auth/me', headers={'Origin': PORTAL})
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(unauthorized.headers['Access-Control-Allow-Origin'], '*')

    @mute_logger('odoo.http')
    def test_unhandled_error_keeps_cors_headers(self):
        resp = self.url_open('/api/v1/auth/login', data='not json', headers={
            'Origin': PORTAL, 'Content-Type': 'application/json',
        })
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.headers['Access-Control-Allow-Origin'], '*')

    def test_allowlist_echoes_only_listed_origins(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'bxi_api.cors_allowed_origins', f'{PORTAL}/, https://other.example.com')
        resp = self._preflight('/api/v1/auth/login')
        self.assertEqual(resp.headers['Access-Control-Allow-Origin'], PORTAL)
        self.assertEqual(resp.headers['Vary'], 'Origin')
        self.assertEqual(self._login().headers['Access-Control-Allow-Origin'], PORTAL)

        stranger = self._preflight('/api/v1/auth/login', origin='https://evil.example.com')
        self.assertNotIn('Access-Control-Allow-Origin', stranger.headers)
        self.assertNotIn('Access-Control-Allow-Origin', self._login(origin='https://evil.example.com').headers)

    def test_no_origin_no_cors_headers(self):
        resp = self.url_open('/api/v1/auth/login', json={
            'login': 'bxi_api_cors_user', 'password': 'Str0ngPassw0rd!',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('Access-Control-Allow-Origin', resp.headers)

    def test_non_api_routes_untouched(self):
        resp = self.url_open('/web/login', headers={'Origin': PORTAL})
        self.assertNotIn('Access-Control-Allow-Origin', resp.headers)
