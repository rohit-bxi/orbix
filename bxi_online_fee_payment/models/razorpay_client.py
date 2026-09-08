# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

import hashlib
import hmac
import logging

import requests

from odoo import models

_logger = logging.getLogger(__name__)

RAZORPAY_ORDERS_URL = 'https://api.razorpay.com/v1/orders'


class RazorpayClient(models.AbstractModel):
    """Thin wrapper around Razorpay's Orders API and its signature schemes.
    The mobile app owns the checkout UI and the Razorpay SDK; this class is
    only ever called from bxi.payment.order to create an order and to
    verify that a reported payment genuinely came from Razorpay.
    """
    _name = 'bxi.razorpay.client'
    _description = 'Razorpay API Client'

    def _get_config(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'key_id': ICP.get_param('bxi_online_fee_payment.razorpay_key_id'),
            'key_secret': ICP.get_param('bxi_online_fee_payment.razorpay_key_secret'),
            'webhook_secret': ICP.get_param('bxi_online_fee_payment.razorpay_webhook_secret'),
        }

    def is_configured(self):
        config = self._get_config()
        return bool(config['key_id'] and config['key_secret'])

    def create_order(self, amount, currency, receipt):
        """`amount` is in the currency's major unit (e.g. rupees) - Razorpay
        wants the minor unit (paise), so it's converted here. Returns the
        Razorpay order dict on success, or None on failure (logged, never
        raised - the caller decides how to surface that to the app).
        """
        config = self._get_config()
        if not config['key_id'] or not config['key_secret']:
            _logger.warning('Razorpay is not configured (missing key id/secret) - order not created.')
            return None

        payload = {
            'amount': int(round(amount * 100)),
            'currency': currency,
            'receipt': receipt,
            'payment_capture': 1,
        }
        try:
            response = requests.post(
                RAZORPAY_ORDERS_URL,
                json=payload,
                auth=(config['key_id'], config['key_secret']),
                timeout=10,
            )
        except requests.RequestException:
            _logger.exception('Razorpay create_order request failed for receipt %s.', receipt)
            return None

        if response.status_code >= 400:
            _logger.warning('Razorpay create_order failed for receipt %s: %s %s', receipt, response.status_code, response.text)
            return None
        return response.json()

    def verify_payment_signature(self, razorpay_order_id, razorpay_payment_id, razorpay_signature):
        """Per Razorpay's checkout flow: expected_signature =
        HMAC-SHA256(order_id + '|' + payment_id, key_secret).
        """
        config = self._get_config()
        if not config['key_secret']:
            return False
        message = f'{razorpay_order_id}|{razorpay_payment_id}'
        expected = hmac.new(config['key_secret'].encode(), message.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, razorpay_signature or '')

    def verify_webhook_signature(self, raw_body, razorpay_signature):
        """Per Razorpay's webhook scheme: expected_signature =
        HMAC-SHA256(raw request body, webhook_secret).
        """
        config = self._get_config()
        if not config['webhook_secret']:
            return False
        expected = hmac.new(config['webhook_secret'].encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, razorpay_signature or '')
