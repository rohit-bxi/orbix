# -*- coding: utf-8 -*-

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.bxi_notification_gateway.models.msg91_client import Msg91Client
from odoo.addons.bxi_notification_gateway.models.otp_request import OTP_MAX_ATTEMPTS

CAPTURED = {}


def _fake_send_otp_sms_ok(self, phone, otp_code):
    CAPTURED['phone'] = phone
    CAPTURED['code'] = otp_code
    return True


def _fake_send_otp_sms_fail(self, phone, otp_code):
    CAPTURED['phone'] = phone
    CAPTURED['code'] = otp_code
    return False


@tagged('post_install', '-at_install')
class TestBxiOtpRequestModel(TransactionCase):
    """Model-level unit tests for bxi.otp.request, calling the model
    methods directly rather than through the HTTP controllers (those are
    covered separately in tests/test_otp.py).
    """

    def setUp(self):
        super().setUp()
        CAPTURED.clear()
        self.Otp = self.env['bxi.otp.request']

    # -- BxiOtpRequest._hash -------------------------------------------

    def test_hash_is_deterministic_sha256(self):
        import hashlib
        code = '123456'
        expected = hashlib.sha256(code.encode()).hexdigest()
        self.assertEqual(self.Otp._hash(code), expected)

    def test_hash_differs_for_different_codes(self):
        self.assertNotEqual(self.Otp._hash('111111'), self.Otp._hash('222222'))

    # -- BxiOtpRequest._generate_and_send -------------------------------

    @patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms_ok)
    def test_generate_and_send_creates_record_and_returns_true_on_success(self):
        result = self.Otp._generate_and_send('+919876543210')

        self.assertTrue(result)
        otp = self.Otp.sudo().search([('phone', '=', '+919876543210')])
        self.assertEqual(len(otp), 1)
        self.assertEqual(otp.purpose, 'login')
        self.assertEqual(otp.attempts, 0)
        self.assertFalse(otp.verified_at)
        self.assertEqual(otp.code_hash, self.Otp._hash(CAPTURED['code']))
        self.assertEqual(len(CAPTURED['code']), 6)

    @patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms_fail)
    def test_generate_and_send_still_creates_record_when_send_fails(self):
        result = self.Otp._generate_and_send('+919876543211')

        self.assertFalse(result)
        otp = self.Otp.sudo().search([('phone', '=', '+919876543211')])
        self.assertEqual(len(otp), 1)

    @patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms_ok)
    def test_generate_and_send_sets_expiry_about_ten_minutes_ahead(self):
        before = fields.Datetime.now()
        self.Otp._generate_and_send('+919876543212')
        otp = self.Otp.sudo().search([('phone', '=', '+919876543212')])

        delta = otp.expires_at - before
        self.assertTrue(timedelta(minutes=9) < delta <= timedelta(minutes=10, seconds=5))

    # -- BxiOtpRequest._verify -------------------------------------------

    def test_verify_returns_not_found_when_no_request_exists(self):
        ok, reason = self.Otp._verify('+910000000000', '123456')
        self.assertFalse(ok)
        self.assertEqual(reason, 'not_found')

    @patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms_ok)
    def test_verify_returns_expired_when_past_expiry(self):
        self.Otp._generate_and_send('+919876543213')
        otp = self.Otp.sudo().search([('phone', '=', '+919876543213')])
        otp.expires_at = fields.Datetime.now() - timedelta(minutes=1)

        ok, reason = self.Otp._verify('+919876543213', CAPTURED['code'])
        self.assertFalse(ok)
        self.assertEqual(reason, 'expired')

    @patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms_ok)
    def test_verify_returns_too_many_attempts_after_max_attempts(self):
        self.Otp._generate_and_send('+919876543214')
        otp = self.Otp.sudo().search([('phone', '=', '+919876543214')])
        otp.attempts = OTP_MAX_ATTEMPTS

        ok, reason = self.Otp._verify('+919876543214', CAPTURED['code'])
        self.assertFalse(ok)
        self.assertEqual(reason, 'too_many_attempts')

    @patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms_ok)
    def test_verify_returns_invalid_code_and_increments_attempts_on_wrong_code(self):
        self.Otp._generate_and_send('+919876543215')
        otp = self.Otp.sudo().search([('phone', '=', '+919876543215')])

        ok, reason = self.Otp._verify('+919876543215', '000000')
        self.assertFalse(ok)
        self.assertEqual(reason, 'invalid_code')
        self.assertEqual(otp.attempts, 1)
        self.assertFalse(otp.verified_at)

    @patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms_ok)
    def test_verify_returns_true_and_sets_verified_at_on_correct_code(self):
        self.Otp._generate_and_send('+919876543216')
        otp = self.Otp.sudo().search([('phone', '=', '+919876543216')])

        ok, reason = self.Otp._verify('+919876543216', CAPTURED['code'])
        self.assertTrue(ok)
        self.assertIsNone(reason)
        self.assertTrue(otp.verified_at)
        self.assertEqual(otp.attempts, 1)

    @patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms_ok)
    def test_verify_cannot_be_reused_after_success(self):
        self.Otp._generate_and_send('+919876543217')
        code = CAPTURED['code']

        first_ok, _ = self.Otp._verify('+919876543217', code)
        self.assertTrue(first_ok)

        second_ok, second_reason = self.Otp._verify('+919876543217', code)
        self.assertFalse(second_ok)
        self.assertEqual(second_reason, 'not_found')
