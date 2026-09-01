from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, tagged

from odoo.addons.bxi_notification_gateway.models.msg91_client import Msg91Client

CAPTURED = {}


def _fake_send_otp_sms(self, phone, otp_code):
    CAPTURED['phone'] = phone
    CAPTURED['code'] = otp_code
    return True


@tagged('post_install', '-at_install')
class TestBxiOtp(HttpCase):

    def setUp(self):
        super().setUp()
        CAPTURED.clear()

    @patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms)
    def test_request_otp_sends_and_returns_sent_true(self):
        resp = self.url_open('/api/v1/otp/request', json={'phone': '+919876543210'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['data']['sent'])
        self.assertEqual(CAPTURED['phone'], '+919876543210')
        self.assertEqual(len(CAPTURED['code']), 6)

    def test_request_otp_missing_phone_rejected(self):
        resp = self.url_open('/api/v1/otp/request', method='POST', json={})
        self.assertEqual(resp.status_code, 400)

    @patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms)
    def test_verify_otp_correct_code_succeeds(self):
        self.url_open('/api/v1/otp/request', json={'phone': '+919876543210'})
        code = CAPTURED['code']

        resp = self.url_open('/api/v1/otp/verify', json={'phone': '+919876543210', 'otp': code})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['data']['verified'])

    @patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms)
    def test_verify_otp_wrong_code_rejected(self):
        self.url_open('/api/v1/otp/request', json={'phone': '+919876543210'})

        resp = self.url_open('/api/v1/otp/verify', json={'phone': '+919876543210', 'otp': '000000'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_code')

    def test_verify_otp_no_request_rejected(self):
        resp = self.url_open('/api/v1/otp/verify', json={'phone': '+910000000000', 'otp': '123456'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'not_found')

    @patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms)
    def test_verify_otp_cannot_be_reused(self):
        self.url_open('/api/v1/otp/request', json={'phone': '+919876543210'})
        code = CAPTURED['code']

        first = self.url_open('/api/v1/otp/verify', json={'phone': '+919876543210', 'otp': code})
        self.assertEqual(first.status_code, 200)

        second = self.url_open('/api/v1/otp/verify', json={'phone': '+919876543210', 'otp': code})
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()['error']['code'], 'not_found')

    @patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms)
    def test_verify_otp_locks_out_after_max_attempts(self):
        self.url_open('/api/v1/otp/request', json={'phone': '+919876543210'})

        for _ in range(5):
            resp = self.url_open('/api/v1/otp/verify', json={'phone': '+919876543210', 'otp': '000000'})
            self.assertEqual(resp.json()['error']['code'], 'invalid_code')

        resp = self.url_open('/api/v1/otp/verify', json={'phone': '+919876543210', 'otp': CAPTURED['code']})
        self.assertEqual(resp.json()['error']['code'], 'too_many_attempts')

    def test_request_otp_not_configured_reports_not_sent(self):
        resp = self.url_open('/api/v1/otp/request', json={'phone': '+919876543210'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['data']['sent'])

    def test_request_otp_blank_phone_rejected(self):
        resp = self.url_open('/api/v1/otp/request', json={'phone': '   '})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_phone')

    def test_verify_otp_missing_phone_rejected(self):
        resp = self.url_open('/api/v1/otp/verify', json={'otp': '123456'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_fields')

    def test_verify_otp_missing_otp_rejected(self):
        resp = self.url_open('/api/v1/otp/verify', json={'phone': '+919876543210'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_fields')

    @patch.object(Msg91Client, 'send_otp_sms', _fake_send_otp_sms)
    def test_verify_otp_expired_rejected(self):
        self.url_open('/api/v1/otp/request', json={'phone': '+919876543210'})
        code = CAPTURED['code']

        otp = self.env['bxi.otp.request'].sudo().search(
            [('phone', '=', '+919876543210')], order='create_date desc', limit=1)
        otp.expires_at = fields.Datetime.now() - timedelta(minutes=1)

        resp = self.url_open('/api/v1/otp/verify', json={'phone': '+919876543210', 'otp': code})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'expired')
