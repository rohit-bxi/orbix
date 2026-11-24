# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, json_field, rate_limit, require_auth
from odoo.addons.bxi_api.controllers.main import BxiApiAuthController


def _resolve_single_user(phone):
    """(user, None) for the one account behind `phone`, else (None, error).
    A number shared by two accounts is refused rather than guessed."""
    users = request.env['res.users'].sudo()._bxi_find_users_by_phone(phone)
    if not users:
        return None, api_error('No account is registered with this phone number.', status=404, code='no_account')
    if len(users) > 1:
        return None, api_error(
            'This phone number is linked to more than one account. Please log in with your username.',
            status=409, code='ambiguous_phone')
    return users, None


def _channel_name(channels):
    return 'both' if len(channels) > 1 else channels[0]


def _mask_email(email):
    """'piyush.mathur@nzeroone.com' -> 'pi****@nzeroone.com'."""
    if not email or '@' not in email:
        return None
    local, domain = email.rsplit('@', 1)
    return '%s****@%s' % (local[:2], domain)


class BxiOtpController(http.Controller):

    @http.route('/api/v1/otp/request', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('otp_request', limit=5)
    def request_otp(self, **kwargs):
        payload = request.get_json_data()
        phone = (payload.get('phone') or '').strip()
        if not phone:
            return api_error('phone is required.', status=400, code='missing_phone')

        Otp = request.env['bxi.otp.request'].sudo()
        channels = Otp._delivery_channels()
        users = request.env['res.users'].sudo()._bxi_find_users_by_phone(phone)
        result = Otp._generate_and_deliver(phone, users if len(users) == 1 else None)
        if 'email' in channels:
            # Emailed codes go to the account behind the number: answer the
            # same whether or not there is one, so the route can't be used
            # to find out which numbers are registered.
            return api_response({'sent': True, 'channel': _channel_name(channels)})
        return api_response({'sent': result['sent'], 'channel': 'sms'})

    @http.route('/api/v1/otp/verify', type='http', auth='public', methods=['POST'], csrf=False)
    # Each code already allows only a few attempts; this also caps how
    # fast one IP can try codes for a phone number.
    @rate_limit('otp_verify', limit=10, key=json_field('phone'))
    def verify_otp(self, **kwargs):
        payload = request.get_json_data()
        phone = (payload.get('phone') or '').strip()
        code = (payload.get('otp') or '').strip()
        if not phone or not code:
            return api_error('phone and otp are required.', status=400, code='missing_fields')

        ok, reason = request.env['bxi.otp.request'].sudo()._verify(phone, code)
        if not ok:
            return api_error('OTP verification failed.', status=400, code=reason)
        return api_response({'verified': True})

    @http.route('/api/v1/auth/otp-login', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('otp_login', limit=10)
    def otp_login(self, **kwargs):
        """Second step of phone login, after /otp/request. The OTP is
        checked (and consumed) before the phone is matched to an account,
        so this route can't be used to probe which numbers are registered.
        """
        payload = request.get_json_data()
        phone = (payload.get('phone') or '').strip()
        code = (payload.get('otp') or '').strip()
        if not phone or not code:
            return api_error('phone and otp are required.', status=400, code='missing_fields')

        ok, reason = request.env['bxi.otp.request'].sudo()._verify(phone, code)
        if not ok:
            return api_error('OTP verification failed.', status=400, code=reason)
        user, error = _resolve_single_user(phone)
        if error:
            return error
        return api_response(BxiApiAuthController._issue_login_response(
            user, payload.get('device_name'), auth_method='otp'))

    @http.route('/api/v1/auth/step-up/otp-request', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('step_up_otp', limit=5)
    @require_auth
    def request_step_up_otp(self, **kwargs):
        """Send an OTP to the logged-in account's own phone (SMS) or email,
        to be sent to POST /api/v1/auth/step-up as `otp`. The number and
        address are never taken from the request, so this can't be pointed
        at someone else."""
        user = request.env.user.sudo()
        phone = user._bxi_get_otp_phone()
        result = request.env['bxi.otp.request'].sudo()._generate_and_deliver(phone, user, purpose='step_up')
        if result['reason'] == 'no_phone':
            return api_error('No phone number is registered on this account. Use your password.',
                             status=400, code='no_phone')
        if result['reason'] in ('no_email', 'no_contact'):
            return api_error('No email address is registered on this account. Use your password.',
                             status=400, code='no_email')
        if result['reason'] == 'throttled':
            return api_error('A code was sent less than a minute ago. Use that code or try again shortly.',
                             status=429, code='otp_throttled')
        by_sms = result['channel'] in ('sms', 'both')
        by_email = result['channel'] in ('email', 'both')
        digits = ''.join(ch for ch in phone or '' if ch.isdigit())
        return api_response({
            'sent': result['sent'], 'channel': result['channel'],
            'phone_hint': '******' + digits[-4:] if by_sms and digits else None,
            'email_hint': _mask_email(result['email']) if by_email else None,
        })

    @http.route('/api/v1/auth/password/forgot', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('password_forgot', limit=5)
    def forgot_password(self, **kwargs):
        """Sends a password-reset OTP to the account's phone (SMS) or email.
        Always answers `requested: true`, whether or not the account
        exists, so it can't be used to discover registered logins or
        numbers."""
        payload = request.get_json_data()
        phone = (payload.get('phone') or '').strip()
        login = (payload.get('login') or '').strip()
        if not phone and not login:
            return api_error('phone or login is required.', status=400, code='missing_fields')

        user, phone = self._reset_target(phone, login)
        if user:
            request.env['bxi.otp.request'].sudo()._generate_and_deliver(phone, user, purpose='password_reset')
        channels = request.env['bxi.otp.request'].sudo()._delivery_channels()
        return api_response({'requested': True, 'channel': _channel_name(channels)})

    @http.route('/api/v1/auth/password/reset', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('password_reset', limit=10)
    def reset_password(self, **kwargs):
        payload = request.get_json_data()
        phone = (payload.get('phone') or '').strip()
        login = (payload.get('login') or '').strip()
        code = (payload.get('otp') or '').strip()
        new_password = payload.get('new_password') or ''
        if not (phone or login) or not code or not new_password:
            return api_error(
                'phone or login, otp and new_password are required.', status=400, code='missing_fields')

        user, phone = self._reset_target(phone, login)
        if not user:
            return api_error('OTP verification failed.', status=400, code='not_found')
        ok, reason = request.env['bxi.otp.request'].sudo()._verify(phone, code, purpose='password_reset', user=user)
        if not ok:
            return api_error('OTP verification failed.', status=400, code=reason)
        try:
            user.sudo()._change_password(new_password)
        except UserError as exc:
            return api_error(str(exc), status=400, code='invalid_password')
        # Whoever had a token for this account before the reset loses it.
        request.env['bxi.api.token']._revoke_all_for_user(user)
        return api_response({'reset': True})

    @staticmethod
    def _reset_target(phone, login):
        """(user, phone_to_text) for a reset request, or (None, None). By
        login, the OTP goes to the phone (or email) on that account - phone
        may then be False."""
        if login:
            user = request.env['res.users'].sudo().search([('login', '=', login)], limit=1)
            return (user, user._bxi_get_otp_phone() or False) if user else (None, None)
        users = request.env['res.users'].sudo()._bxi_find_users_by_phone(phone)
        return (users, phone) if len(users) == 1 else (None, None)
