# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Two-factor authentication for the app, on Odoo's own authenticator-app
2FA (auth_totp): the same secret signs in to the website and the app.

Set-up: /auth/2fa/setup (QR code + secret) then /auth/2fa/enable with the
first 6-digit code. Once on, a password /auth/login answers
{"mfa_required": true, "mfa_token": ...} instead of a token, and
/auth/login/2fa trades that mfa_token plus the current code for the token.
"""
import base64
import os
import time

from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.tools.misc import consteq, hmac

from .auth import api_error, api_response, json_field, rate_limit, require_auth, require_recent_auth

MFA_TOKEN_TTL = 300
MFA_SCOPE = 'bxi_api.login_2fa'
TOTP_SECRET_BYTES = 160 // 8


def _sign(env, uid, expires):
    return hmac(env(su=True), MFA_SCOPE, '%s.%s' % (uid, expires))


def make_mfa_token(user):
    """A short-lived proof that `user` just passed the password step."""
    expires = int(time.time()) + MFA_TOKEN_TTL
    return '%s.%s.%s' % (user.id, expires, _sign(request.env, user.id, expires))


def read_mfa_token(token):
    """The res.users (sudo) an mfa_token was issued to, or None when it is
    malformed, forged or expired."""
    try:
        uid, expires, signature = (token or '').split('.')
        uid, expires = int(uid), int(expires)
    except ValueError:
        return None
    if expires < time.time() or not consteq(signature, _sign(request.env, uid, expires)):
        return None
    user = request.env['res.users'].sudo().browse(uid).exists()
    return user if user and user.active else None


def _code(payload):
    raw = str(payload.get('code') or '').replace(' ', '')
    return int(raw) if raw.isdigit() and len(raw) == 6 else None


def check_totp(user, code):
    """True when `code` is the user's current authenticator code (Odoo's
    own check: rate-limited per IP/user, and a code can't be reused)."""
    try:
        user.with_user(user)._check_credentials({'type': 'totp', 'token': code}, {'interactive': False})
    except AccessDenied:
        return False
    return True


class BxiApiTwoFactorController(http.Controller):

    @http.route('/api/v1/auth/login/2fa', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('login_2fa', limit=10, key=json_field('mfa_token'))
    def login_2fa(self, **kwargs):
        """Second login step: {"mfa_token", "code", "device_name"?} ->
        the same body as /auth/login."""
        from .main import BxiApiAuthController

        payload = request.get_json_data() or {}
        code = _code(payload)
        if not payload.get('mfa_token') or code is None:
            return api_error('mfa_token and a 6-digit code are required.', status=400, code='missing_credentials')
        user = read_mfa_token(payload['mfa_token'])
        if not user:
            return api_error('This sign-in has expired. Log in again.', status=401, code='mfa_token_expired')
        if not user.totp_enabled:
            return api_error('Two-factor authentication is off for this account.', status=400,
                             code='2fa_not_enabled')
        if not check_totp(user, code):
            return api_error('Wrong or expired code.', status=401, code='invalid_code')
        return api_response(BxiApiAuthController._issue_login_response(user, payload.get('device_name')))

    @http.route('/api/v1/auth/2fa', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def status(self, **kwargs):
        return api_response({'enabled': request.env.user.sudo().totp_enabled})

    @http.route('/api/v1/auth/2fa/setup', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @require_recent_auth
    def setup(self, **kwargs):
        """Start set-up: a new secret as a QR code (PNG, base64) and as text
        for typing into an authenticator app. Nothing changes until
        /auth/2fa/enable confirms a code."""
        user = request.env.user
        if user.sudo().totp_enabled:
            return api_error('Two-factor authentication is already on.', status=400, code='2fa_already_enabled')
        secret = base64.b32encode(os.urandom(TOTP_SECRET_BYTES)).decode()
        secret = ' '.join(map(''.join, zip(*[iter(secret)] * 4)))
        wizard = request.env['auth_totp.wizard'].sudo().create({'user_id': user.id, 'secret': secret})
        return api_response({
            'setup_id': wizard.id,
            'secret': secret,
            'otpauth_url': wizard.url,
            'qr_code_png_base64': wizard.qrcode.decode() if isinstance(wizard.qrcode, bytes) else wizard.qrcode,
        })

    @http.route('/api/v1/auth/2fa/enable', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('2fa_enable', limit=10)
    @require_auth
    def enable(self, **kwargs):
        """{"setup_id", "code"}: the first code from the authenticator app
        turns two-factor authentication on."""
        payload = request.get_json_data() or {}
        code = _code(payload)
        try:
            setup_id = int(payload.get('setup_id'))
        except (TypeError, ValueError):
            setup_id = None
        if not setup_id or code is None:
            return api_error('setup_id and a 6-digit code are required.', status=400, code='missing_fields')
        user = request.env.user
        wizard = request.env['auth_totp.wizard'].sudo().browse(setup_id).exists()
        if not wizard or wizard.user_id != user or not wizard.secret:
            return api_error('Set-up not found: start again.', status=404, code='not_found')
        if not user._totp_try_setting(wizard.secret, code):
            return api_error('Wrong code: check the time on your phone and try the newest code.',
                             status=400, code='invalid_code')
        wizard.secret = ''
        return api_response({'enabled': True})

    @http.route('/api/v1/auth/2fa/disable', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('2fa_disable', limit=10)
    @require_auth
    @require_recent_auth
    def disable(self, **kwargs):
        """{"code"}: turn two-factor authentication off. Needs a recent
        password confirmation (/auth/step-up) and a current code."""
        user = request.env.user.sudo()
        if not user.totp_enabled:
            return api_error('Two-factor authentication is already off.', status=400, code='2fa_not_enabled')
        code = _code(request.get_json_data() or {})
        if code is None:
            return api_error('A 6-digit code is required.', status=400, code='missing_fields')
        if not check_totp(user, code):
            return api_error('Wrong or expired code.', status=401, code='invalid_code')
        user.write({'totp_secret': False})
        return api_response({'enabled': False})
