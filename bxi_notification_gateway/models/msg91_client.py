# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

import logging

import requests

from odoo import models

_logger = logging.getLogger(__name__)

MSG91_FLOW_URL = 'https://api.msg91.com/api/v5/flow/'


class Msg91Client(models.AbstractModel):
    """Thin wrapper around MSG91's Flow (template) SMS API.

    Odoo generates and verifies the OTP code itself (see bxi.otp.request) -
    MSG91 is only used to deliver the SMS, via a flow/template that expects
    an ``OTP`` variable. Kept as a single method so it's easy to mock in
    tests and easy to swap for a different provider later without touching
    calling code.
    """
    _name = 'bxi.msg91.client'
    _description = 'MSG91 SMS Client'

    def _get_config(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'auth_key': ICP.get_param('bxi_notification_gateway.msg91_auth_key'),
            'sender_id': ICP.get_param('bxi_notification_gateway.msg91_sender_id'),
            'template_id': ICP.get_param('bxi_notification_gateway.msg91_otp_template_id'),
        }

    def send_otp_sms(self, phone, otp_code):
        """Send `otp_code` to `phone` via the configured MSG91 OTP template.
        Returns True on a 2xx response from MSG91, False otherwise (never
        raises - a failed send should not break the caller's flow, it
        should just be logged and surfaced as `sent: false`).
        """
        config = self._get_config()
        if not config['auth_key'] or not config['template_id']:
            _logger.warning('MSG91 is not configured (missing auth key or template id) - OTP SMS to %s not sent.', phone)
            return False

        payload = {
            'template_id': config['template_id'],
            'short_url': '0',
            'recipients': [{
                'mobiles': phone,
                'OTP': otp_code,
            }],
        }
        if config['sender_id']:
            payload['sender'] = config['sender_id']

        try:
            response = requests.post(
                MSG91_FLOW_URL,
                json=payload,
                headers={'authkey': config['auth_key'], 'Content-Type': 'application/json'},
                timeout=10,
            )
        except requests.RequestException:
            _logger.exception('MSG91 OTP SMS request failed for %s.', phone)
            return False

        if response.status_code >= 400:
            _logger.warning('MSG91 OTP SMS to %s failed: %s %s', phone, response.status_code, response.text)
            return False
        return True
