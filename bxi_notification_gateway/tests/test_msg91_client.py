# -*- coding: utf-8 -*-

from unittest.mock import MagicMock, patch

import requests

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMsg91Client(TransactionCase):
    """Unit tests for bxi.msg91.client._get_config/send_otp_sms, covering the
    HTTP-layer branches (success, MSG91 error response, network failure) that
    the controller/OTP flow tests don't exercise directly since they stop at
    the "not configured" short-circuit.
    """

    def setUp(self):
        super().setUp()
        self.client = self.env['bxi.msg91.client'].sudo()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('bxi_notification_gateway.msg91_auth_key', 'test-auth-key')
        ICP.set_param('bxi_notification_gateway.msg91_sender_id', 'ORBIX')
        ICP.set_param('bxi_notification_gateway.msg91_otp_template_id', 'template-123')

    def test_send_otp_sms_missing_auth_key_returns_false(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_notification_gateway.msg91_auth_key', '')
        with patch('odoo.addons.bxi_notification_gateway.models.msg91_client.requests.post') as mock_post:
            result = self.client.send_otp_sms('+919876543210', '123456')
        self.assertFalse(result)
        mock_post.assert_not_called()

    def test_send_otp_sms_missing_template_id_returns_false(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_notification_gateway.msg91_otp_template_id', '')
        with patch('odoo.addons.bxi_notification_gateway.models.msg91_client.requests.post') as mock_post:
            result = self.client.send_otp_sms('+919876543210', '123456')
        self.assertFalse(result)
        mock_post.assert_not_called()

    def test_send_otp_sms_success_includes_sender_id_in_payload(self):
        mock_response = MagicMock(status_code=200, text='{"type":"success"}')
        with patch('odoo.addons.bxi_notification_gateway.models.msg91_client.requests.post',
                   return_value=mock_response) as mock_post:
            result = self.client.send_otp_sms('+919876543210', '654321')

        self.assertTrue(result)
        mock_post.assert_called_once()
        _args, kwargs = mock_post.call_args
        self.assertEqual(kwargs['json']['sender'], 'ORBIX')
        self.assertEqual(kwargs['json']['template_id'], 'template-123')
        self.assertEqual(kwargs['json']['recipients'][0]['mobiles'], '+919876543210')
        self.assertEqual(kwargs['json']['recipients'][0]['OTP'], '654321')
        self.assertEqual(kwargs['headers']['authkey'], 'test-auth-key')

    def test_send_otp_sms_omits_sender_when_not_configured(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_notification_gateway.msg91_sender_id', '')
        mock_response = MagicMock(status_code=200, text='{"type":"success"}')
        with patch('odoo.addons.bxi_notification_gateway.models.msg91_client.requests.post',
                   return_value=mock_response) as mock_post:
            self.client.send_otp_sms('+919876543210', '654321')

        _args, kwargs = mock_post.call_args
        self.assertNotIn('sender', kwargs['json'])

    def test_send_otp_sms_msg91_error_response_returns_false(self):
        mock_response = MagicMock(status_code=422, text='{"type":"error","message":"invalid mobile"}')
        with patch('odoo.addons.bxi_notification_gateway.models.msg91_client.requests.post',
                   return_value=mock_response):
            result = self.client.send_otp_sms('+919876543210', '654321')
        self.assertFalse(result)

    def test_send_otp_sms_network_failure_returns_false(self):
        with patch('odoo.addons.bxi_notification_gateway.models.msg91_client.requests.post',
                   side_effect=requests.ConnectionError('boom')):
            result = self.client.send_otp_sms('+919876543210', '654321')
        self.assertFalse(result)
