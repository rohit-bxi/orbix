from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestBxiApiAuth(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_user = cls.env['res.users'].create({
            'name': 'API Test User',
            'login': 'bxi_api_test_user',
            'password': 'Str0ngPassw0rd!',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def test_login_returns_token_and_user(self):
        resp = self.url_open('/api/v1/auth/login', json={
            'login': 'bxi_api_test_user', 'password': 'Str0ngPassw0rd!',
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['success'])
        self.assertTrue(body['data']['token'].startswith('orb_'))
        self.assertEqual(body['data']['user']['login'], 'bxi_api_test_user')

    def test_login_wrong_password_rejected(self):
        resp = self.url_open('/api/v1/auth/login', json={
            'login': 'bxi_api_test_user', 'password': 'wrong-password',
        })
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(resp.json()['success'])

    def test_login_missing_fields_rejected(self):
        resp = self.url_open('/api/v1/auth/login', json={'login': 'bxi_api_test_user'})
        self.assertEqual(resp.status_code, 400)

    def test_me_requires_valid_token(self):
        resp = self.url_open('/api/v1/auth/me', headers={'Authorization': 'Bearer not-a-real-token'})
        self.assertEqual(resp.status_code, 401)

        resp = self.url_open('/api/v1/auth/me')
        self.assertEqual(resp.status_code, 401)

    def test_me_resolves_to_logged_in_user(self):
        login_resp = self.url_open('/api/v1/auth/login', json={
            'login': 'bxi_api_test_user', 'password': 'Str0ngPassw0rd!',
        })
        token = login_resp.json()['data']['token']

        me_resp = self.url_open('/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(me_resp.status_code, 200)
        self.assertEqual(me_resp.json()['data']['login'], 'bxi_api_test_user')

    def test_logout_revokes_token(self):
        login_resp = self.url_open('/api/v1/auth/login', json={
            'login': 'bxi_api_test_user', 'password': 'Str0ngPassw0rd!',
        })
        token = login_resp.json()['data']['token']
        headers = {'Authorization': f'Bearer {token}'}

        logout_resp = self.url_open('/api/v1/auth/logout', method='POST', headers=headers)
        self.assertEqual(logout_resp.status_code, 200)

        me_resp = self.url_open('/api/v1/auth/me', headers=headers)
        self.assertEqual(me_resp.status_code, 401)

    def test_expired_token_rejected(self):
        login_resp = self.url_open('/api/v1/auth/login', json={
            'login': 'bxi_api_test_user', 'password': 'Str0ngPassw0rd!',
        })
        token = login_resp.json()['data']['token']
        Token = self.env['bxi.api.token'].sudo()
        record = Token.search([('token_hash', '=', Token._hash(token))], limit=1)
        record.write({'expires_at': '2000-01-01 00:00:00'})

        resp = self.url_open('/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(resp.status_code, 401)

    def test_login_nonexistent_user_rejected(self):
        resp = self.url_open('/api/v1/auth/login', json={
            'login': 'no-such-user', 'password': 'whatever',
        })
        self.assertEqual(resp.status_code, 401)
        body = resp.json()
        self.assertFalse(body['success'])
        self.assertEqual(body['error']['code'], 'invalid_credentials')

    def test_login_missing_password_rejected(self):
        resp = self.url_open('/api/v1/auth/login', json={'password': 'Str0ngPassw0rd!'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_credentials')

    def test_login_with_device_name_sets_token_label(self):
        resp = self.url_open('/api/v1/auth/login', json={
            'login': 'bxi_api_test_user', 'password': 'Str0ngPassw0rd!',
            'device_name': "Parent app - Test phone",
        })
        token = resp.json()['data']['token']
        Token = self.env['bxi.api.token'].sudo()
        record = Token.search([('token_hash', '=', Token._hash(token))], limit=1)
        self.assertEqual(record.name, "Parent app - Test phone")

    def test_logout_without_token_rejected(self):
        resp = self.url_open('/api/v1/auth/logout', method='POST')
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(resp.json()['success'])

    def test_logout_with_invalid_token_rejected(self):
        resp = self.url_open(
            '/api/v1/auth/logout', method='POST',
            headers={'Authorization': 'Bearer not-a-real-token'},
        )
        self.assertEqual(resp.status_code, 401)

    def test_logout_twice_second_call_unauthorized(self):
        login_resp = self.url_open('/api/v1/auth/login', json={
            'login': 'bxi_api_test_user', 'password': 'Str0ngPassw0rd!',
        })
        token = login_resp.json()['data']['token']
        headers = {'Authorization': f'Bearer {token}'}

        first = self.url_open('/api/v1/auth/logout', method='POST', headers=headers)
        self.assertEqual(first.status_code, 200)

        second = self.url_open('/api/v1/auth/logout', method='POST', headers=headers)
        self.assertEqual(second.status_code, 401)

    def test_new_login_does_not_revoke_previous_token(self):
        first_login = self.url_open('/api/v1/auth/login', json={
            'login': 'bxi_api_test_user', 'password': 'Str0ngPassw0rd!',
        })
        first_token = first_login.json()['data']['token']

        second_login = self.url_open('/api/v1/auth/login', json={
            'login': 'bxi_api_test_user', 'password': 'Str0ngPassw0rd!',
        })
        second_token = second_login.json()['data']['token']

        self.assertNotEqual(first_token, second_token)

        first_me = self.url_open('/api/v1/auth/me', headers={'Authorization': f'Bearer {first_token}'})
        self.assertEqual(first_me.status_code, 200)
        second_me = self.url_open('/api/v1/auth/me', headers={'Authorization': f'Bearer {second_token}'})
        self.assertEqual(second_me.status_code, 200)

    def test_verify_token_returns_empty_for_revoked_token(self):
        raw_token = self.env['bxi.api.token']._issue_for_user(self.test_user, name='Direct model test')
        Token = self.env['bxi.api.token'].sudo()
        record = Token.search([('token_hash', '=', Token._hash(raw_token))], limit=1)
        record.action_revoke()

        resolved_user = Token._verify_token(raw_token)
        self.assertFalse(resolved_user)

    def test_verify_token_returns_empty_for_blank_token(self):
        Token = self.env['bxi.api.token'].sudo()
        self.assertFalse(Token._verify_token(False))
        self.assertFalse(Token._verify_token(''))

    def test_issue_for_user_without_ttl_has_no_expiry(self):
        Token = self.env['bxi.api.token'].sudo()
        raw_token = Token._issue_for_user(self.test_user, name='No expiry device', ttl_days=0)
        record = Token.search([('token_hash', '=', Token._hash(raw_token))], limit=1)
        self.assertFalse(record.expires_at)
        # and it should still authenticate successfully
        resolved_user = Token._verify_token(raw_token)
        self.assertEqual(resolved_user, self.test_user)

    def test_issue_for_user_stores_hash_not_raw_token(self):
        Token = self.env['bxi.api.token'].sudo()
        raw_token = Token._issue_for_user(self.test_user, name='Hash check device')
        record = Token.search([('token_hash', '=', Token._hash(raw_token))], limit=1)
        self.assertNotEqual(record.token_hash, raw_token)
        self.assertEqual(record.token_last4, raw_token[-4:])
