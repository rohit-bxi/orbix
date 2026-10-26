# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

import json
import logging
import time

import requests

from odoo import models

_logger = logging.getLogger(__name__)

FCM_SEND_URL = 'https://fcm.googleapis.com/v1/projects/%s/messages:send'
FCM_SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'

# OAuth access tokens from the service account are valid for an hour;
# cache one per process (keyed by project) instead of minting one per push.
_ACCESS_TOKENS = {}


class FcmClient(models.AbstractModel):
    """Thin wrapper around the FCM HTTP v1 send API, the push counterpart
    of bxi.msg91.client. Only bxi.notification's push cron calls it.
    """
    _name = 'bxi.fcm.client'
    _description = 'Firebase Cloud Messaging Client'

    def _get_config(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'project_id': ICP.get_param('bxi_notification_gateway.fcm_project_id'),
            'service_account_json': ICP.get_param('bxi_notification_gateway.fcm_service_account_json'),
        }

    def is_configured(self):
        config = self._get_config()
        return bool(config['project_id'] and config['service_account_json'])

    def _get_access_token(self, config):
        cached = _ACCESS_TOKENS.get(config['project_id'])
        if cached and cached[1] - 60 > time.time():
            return cached[0]
        # Imported here, not at module load, so a missing library only
        # breaks push sending, never the module's other routes.
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_info(
            json.loads(config['service_account_json']), scopes=[FCM_SCOPE])
        credentials.refresh(Request())
        expiry = credentials.expiry.timestamp() if credentials.expiry else time.time() + 3000
        _ACCESS_TOKENS[config['project_id']] = (credentials.token, expiry)
        return credentials.token

    def send(self, device_token, title, body, data=None):
        """Push one message to one device. Returns 'sent', 'unregistered'
        (the token is dead - caller should deactivate the device) or
        'failed'. Never raises, same contract as send_otp_sms."""
        config = self._get_config()
        if not config['project_id'] or not config['service_account_json']:
            _logger.warning('FCM is not configured (missing project id or service account) - push not sent.')
            return 'failed'
        try:
            access_token = self._get_access_token(config)
        except Exception:
            _logger.exception('Could not obtain an FCM access token for project %s.', config['project_id'])
            return 'failed'

        message = {
            'token': device_token,
            'notification': {'title': title or '', 'body': body or ''},
            # FCM data payload values must all be strings.
            'data': {key: str(value) for key, value in (data or {}).items() if value is not None},
        }
        try:
            response = requests.post(
                FCM_SEND_URL % config['project_id'],
                json={'message': message},
                headers={'Authorization': f'Bearer {access_token}'},
                timeout=10,
            )
        except requests.RequestException:
            _logger.exception('FCM send request failed.')
            return 'failed'

        if response.status_code < 400:
            return 'sent'
        if self._is_unregistered(response):
            return 'unregistered'
        _logger.warning('FCM send failed: %s %s', response.status_code, response.text)
        return 'failed'

    @staticmethod
    def _is_unregistered(response):
        if response.status_code == 404:
            return True
        try:
            details = response.json().get('error', {}).get('details', [])
        except ValueError:
            return False
        # Not INVALID_ARGUMENT: that is also what a malformed payload (our
        # bug) returns, and it must never deactivate every device.
        return any(d.get('errorCode') == 'UNREGISTERED' for d in details)
