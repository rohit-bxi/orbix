# -*- coding: utf-8 -*-

import hashlib
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBxiApiTokenModel(TransactionCase):
    """Model-level unit tests for bxi.api.token, calling the model methods
    directly (env['bxi.api.token'].method(...)) rather than through HTTP
    routes. See tests/test_api_auth.py for the HTTP-level coverage of the
    same behavior - this file is a 1:1 mapping onto the model's methods.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Token = cls.env['bxi.api.token']
        cls.test_user = cls.env['res.users'].create({
            'name': 'API Token Test User',
            'login': 'bxi_api_token_test_user',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    # -- _hash -----------------------------------------------------------

    def test_hash_is_deterministic_sha256(self):
        raw = 'orb_sometoken123'
        expected = hashlib.sha256(raw.encode()).hexdigest()
        self.assertEqual(self.Token._hash(raw), expected)

    def test_hash_different_inputs_differ(self):
        self.assertNotEqual(self.Token._hash('token-a'), self.Token._hash('token-b'))

    # -- _issue_for_user ---------------------------------------------------

    def test_issue_for_user_creates_token_and_returns_raw_value(self):
        raw_token = self.Token._issue_for_user(self.test_user, name='Test Device')
        self.assertTrue(raw_token.startswith('orb_'))

        record = self.Token.sudo().search([('user_id', '=', self.test_user.id)])
        self.assertEqual(len(record), 1)
        self.assertEqual(record.token_hash, self.Token._hash(raw_token))
        self.assertEqual(record.token_last4, raw_token[-4:])
        self.assertEqual(record.name, 'Test Device')
        self.assertTrue(record.active)

    def test_issue_for_user_sets_expiry_from_ttl_days(self):
        before = fields.Datetime.now()
        raw_token = self.Token._issue_for_user(self.test_user, ttl_days=5)
        record = self.Token.sudo().search([('token_hash', '=', self.Token._hash(raw_token))])
        self.assertTrue(record.expires_at)
        self.assertAlmostEqual(
            record.expires_at, before + timedelta(days=5), delta=timedelta(minutes=1)
        )

    def test_issue_for_user_no_expiry_when_ttl_days_falsy(self):
        raw_token = self.Token._issue_for_user(self.test_user, ttl_days=0)
        record = self.Token.sudo().search([('token_hash', '=', self.Token._hash(raw_token))])
        self.assertFalse(record.expires_at)

    def test_issue_for_user_no_name_defaults_to_false(self):
        raw_token = self.Token._issue_for_user(self.test_user)
        record = self.Token.sudo().search([('token_hash', '=', self.Token._hash(raw_token))])
        self.assertFalse(record.name)

    # -- _verify_token -----------------------------------------------------

    def test_verify_token_empty_returns_empty_recordset(self):
        result = self.Token._verify_token(False)
        self.assertFalse(result)
        self.assertEqual(result._name, 'res.users')

    def test_verify_token_unknown_token_returns_empty_recordset(self):
        result = self.Token._verify_token('orb_not-a-real-token')
        self.assertFalse(result)

    def test_verify_token_valid_returns_user_and_bumps_last_used(self):
        raw_token = self.Token._issue_for_user(self.test_user)
        record = self.Token.sudo().search([('token_hash', '=', self.Token._hash(raw_token))])
        self.assertFalse(record.last_used_at)

        result = self.Token._verify_token(raw_token)
        self.assertEqual(result, self.test_user)
        self.assertTrue(record.last_used_at)

    def test_verify_token_revoked_returns_empty_recordset(self):
        raw_token = self.Token._issue_for_user(self.test_user)
        record = self.Token.sudo().search([('token_hash', '=', self.Token._hash(raw_token))])
        record.action_revoke()

        result = self.Token._verify_token(raw_token)
        self.assertFalse(result)

    def test_verify_token_expired_returns_empty_recordset(self):
        raw_token = self.Token._issue_for_user(self.test_user, ttl_days=1)
        record = self.Token.sudo().search([('token_hash', '=', self.Token._hash(raw_token))])
        record.write({'expires_at': fields.Datetime.now() - timedelta(days=1)})

        result = self.Token._verify_token(raw_token)
        self.assertFalse(result)

    # -- action_revoke -----------------------------------------------------

    def test_action_revoke_sets_active_false(self):
        raw_token = self.Token._issue_for_user(self.test_user)
        record = self.Token.sudo().search([('token_hash', '=', self.Token._hash(raw_token))])
        self.assertTrue(record.active)

        record.action_revoke()
        self.assertFalse(record.active)
