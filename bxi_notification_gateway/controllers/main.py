# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, rate_limit
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


class BxiOtpController(http.Controller):

    @http.route('/api/v1/otp/request', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('otp_request', limit=5)
    def request_otp(self, **kwargs):
        payload = request.get_json_data()
        phone = (payload.get('phone') or '').strip()
        if not phone:
            return api_error('phone is required.', status=400, code='missing_phone')

        sent = request.env['bxi.otp.request'].sudo()._generate_and_send(phone)
        return api_response({'sent': sent})

    @http.route('/api/v1/otp/verify', type='http', auth='public', methods=['POST'], csrf=False)
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
        return api_response(BxiApiAuthController._issue_login_response(user, payload.get('device_name')))

    @http.route('/api/v1/auth/password/forgot', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('password_forgot', limit=5)
    def forgot_password(self, **kwargs):
        """Sends a password-reset OTP to the account's phone. Always answers
        `requested: true`, whether or not the account exists, so it can't
        be used to discover registered logins or numbers."""
        payload = request.get_json_data()
        phone = (payload.get('phone') or '').strip()
        login = (payload.get('login') or '').strip()
        if not phone and not login:
            return api_error('phone or login is required.', status=400, code='missing_fields')

        user, phone = self._reset_target(phone, login)
        if user:
            request.env['bxi.otp.request'].sudo()._generate_and_send(phone, purpose='password_reset')
        return api_response({'requested': True})

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
        ok, reason = request.env['bxi.otp.request'].sudo()._verify(phone, code, purpose='password_reset')
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
        login, the OTP goes to the phone on that account."""
        if login:
            user = request.env['res.users'].sudo().search([('login', '=', login)], limit=1)
            user_phone = user and user._bxi_get_otp_phone()
            return (user, user_phone) if user_phone else (None, None)
        users = request.env['res.users'].sudo()._bxi_find_users_by_phone(phone)
        return (users, phone) if len(users) == 1 else (None, None)
