# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Aadhaar login for the Orbix app (see README.md).

The Aadhaar number only finds the account. It is turned into the real
username before Odoo's authenticate() runs, so Odoo's own failed-login
cooldown applies and its log lines never contain the number. Unknown
numbers and wrong passwords get the same answer.
"""
import logging

from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, rate_limit, require_auth
from odoo.addons.bxi_api.controllers.main import BxiApiAuthController
from odoo.addons.bxi_identity_verification.models.aadhaar import clean_aadhaar, looks_like_aadhaar, normalize_aadhaar
from odoo.addons.bxi_notification_gateway.models.otp_request import OTP_TTL_MINUTES

from ..models.res_users import EMAIL_OTP_CREDENTIAL, EmailOtpDenied, mask_email

_logger = logging.getLogger(__name__)

# Testing switch (system parameter, off by default): /aadhaar/otp-request
# also returns the code. Anyone who knows an Aadhaar number can then log in
# as that person - only for testing without a mail server, never with real
# families.
OTP_IN_RESPONSE_PARAM = 'bxi_aadhaar_login.otp_in_response'

SETTING_FIELDS = {
    'enabled': 'bxi_aadhaar_login_enabled',
    'otp_enabled': 'bxi_aadhaar_login_otp_enabled',
    'requires_verified': 'bxi_aadhaar_login_requires_verified',
}
ROLES = ('student', 'teacher', 'parent')


def otp_in_response():
    value = request.env['ir.config_parameter'].sudo().get_param(OTP_IN_RESPONSE_PARAM) or ''
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _invalid_credentials():
    return api_error('Invalid Aadhaar number or password.', status=401, code='invalid_credentials')


def _ambiguous():
    return api_error('This Aadhaar number is linked to more than one account. Please log in with your username.',
                     status=409, code='ambiguous_aadhaar')


def _invalid_aadhaar():
    return api_error('Enter a valid 12-digit Aadhaar number.', status=400, code='invalid_aadhaar')


def is_aadhaar_login(payload):
    """True when a /auth/login body means an Aadhaar number: said so with
    "login_type": "aadhaar", or (no login_type) a valid Aadhaar number
    that is not also somebody's actual username."""
    login_type = payload.get('login_type')
    if login_type:
        return login_type == 'aadhaar'
    login = payload.get('login')
    if not looks_like_aadhaar(login):
        return False
    Users = request.env['res.users'].sudo().with_context(active_test=False)
    return not Users.search_count([('login', 'in', list({login.strip(), clean_aadhaar(login.strip())}))])


def issue_aadhaar_login(user, device_name, auth_method):
    request.update_context(bxi_login_identifier='aadhaar')
    response = BxiApiAuthController._issue_login_response(user, device_name, auth_method=auth_method)
    response['login_identifier'] = 'aadhaar'
    return response


class BxiAadhaarAuthController(BxiApiAuthController):

    @http.route()
    def login(self, **kwargs):
        """Also accepts {"login_type": "aadhaar", "login": "<Aadhaar>",
        "password", "device_name"?} - see is_aadhaar_login."""
        payload = request.get_json_data() or {}
        if isinstance(payload, dict) and is_aadhaar_login(payload):
            return self._aadhaar_password_login(payload)
        return super().login(**kwargs)

    @rate_limit('aadhaar_login', limit=10)
    def _aadhaar_password_login(self, payload):
        number = payload.get('login')
        password = payload.get('password') or ''
        if not number or not password:
            return api_error('login and password are required.', status=400, code='missing_credentials')
        if not normalize_aadhaar(number if isinstance(number, str) else ''):
            return _invalid_aadhaar()
        Users = request.env['res.users'].sudo()
        user, _records, reason = Users._bxi_aadhaar_resolve(number)
        if reason == 'ambiguous':
            return _ambiguous()
        if not user:
            return _invalid_credentials()
        try:
            auth_info = Users.authenticate(
                {'type': 'password', 'login': user.login, 'password': password}, {'interactive': False})
        except AccessDenied:
            return _invalid_credentials()
        user = Users.browse(auth_info['uid'])
        return api_response(issue_aadhaar_login(user, payload.get('device_name'), 'password'))

    @http.route('/api/v1/auth/aadhaar/config', type='http', auth='public', methods=['GET'], csrf=False)
    def aadhaar_config(self, **kwargs):
        """Whether the app should offer Aadhaar login (and the email code)."""
        companies = request.env['res.company'].sudo().search([('bxi_aadhaar_login_enabled', '=', True)])
        return api_response({
            'enabled': bool(companies),
            'otp_enabled': any(companies.mapped('bxi_aadhaar_login_otp_enabled')),
            'otp_channel': 'email',
            'otp_expires_in': OTP_TTL_MINUTES * 60,
        })

    @http.route('/api/v1/auth/aadhaar/otp-request', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('aadhaar_otp_request', limit=5)
    def aadhaar_otp_request(self, **kwargs):
        """{"aadhaar"} -> emails a 6-digit code to the address on the school
        record. Always the same reply - a made-up hint for a number no
        account may use - so it can't be used to find registered numbers.
        Codes are limited to one a minute and five an hour per account; a
        repeat inside that window keeps the previous code valid."""
        payload = request.get_json_data() or {}
        number = payload.get('aadhaar')
        if not isinstance(number, str) or not normalize_aadhaar(number):
            return _invalid_aadhaar()
        Users = request.env['res.users'].sudo()
        user, records, reason = Users._bxi_aadhaar_resolve(number)
        if reason == 'ambiguous':
            return _ambiguous()
        hint = Users._bxi_fake_email_hint(number)
        testing = otp_in_response()
        code = None
        if user and user.company_id.bxi_aadhaar_login_otp_enabled:
            email = user._bxi_aadhaar_otp_email(records)
            Otp = request.env['bxi.otp.request'].sudo()
            if testing:
                # Testing switch: a code even without an email address, and
                # the code itself in the reply.
                _status, code = Otp._generate_and_email(user, email, purpose='login', return_code=True)
                if code:
                    _logger.warning('Aadhaar login testing switch is ON: the login code for user %s was returned '
                                    'in the API response. Switch it off before real use.', user.id)
            elif email:
                Otp._generate_and_email(user, email, purpose='login')
            if email:
                hint = mask_email(email)
        data = {'sent': True, 'channel': 'email', 'email_hint': hint, 'expires_in': OTP_TTL_MINUTES * 60}
        if testing:
            # null for an unknown number, or when the previous code (sent
            # less than a minute ago) is still the one to use.
            data['otp'] = code
        return api_response(data)

    @http.route('/api/v1/auth/aadhaar/otp-login', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('aadhaar_otp_login', limit=10)
    def aadhaar_otp_login(self, **kwargs):
        """{"aadhaar", "otp", "device_name"?} -> the normal login response."""
        payload = request.get_json_data() or {}
        number = payload.get('aadhaar')
        code = str(payload.get('otp') or '').strip()
        if not number or not code:
            return api_error('aadhaar and otp are required.', status=400, code='missing_fields')
        if not isinstance(number, str) or not normalize_aadhaar(number):
            return _invalid_aadhaar()
        Users = request.env['res.users'].sudo()
        user, _records, reason = Users._bxi_aadhaar_resolve(number)
        if reason == 'ambiguous':
            return _ambiguous()
        if not user or not user.company_id.bxi_aadhaar_login_otp_enabled:
            # The same answer a real account gets when it never asked for a code.
            return api_error('OTP verification failed.', status=400, code='not_found')
        try:
            auth_info = Users.authenticate(
                {'type': EMAIL_OTP_CREDENTIAL, 'login': user.login, 'otp': code}, {'interactive': False})
        except EmailOtpDenied as exc:
            return api_error('OTP verification failed.', status=400, code=exc.reason)
        except AccessDenied:
            # Odoo's failed-login cooldown, or an archived account.
            return api_error('OTP verification failed. Please wait a moment and try again.', status=400,
                             code='invalid_code')
        user = Users.browse(auth_info['uid'])
        return api_response(issue_aadhaar_login(user, payload.get('device_name'), 'otp'))

    # -- school settings (system administrators) -------------------------------------------

    @staticmethod
    def _settings_response(company):
        return api_response(dict(company._bxi_aadhaar_settings(), otp_in_response=otp_in_response(),
                                 company={'id': company.id, 'name': company.name}))

    @http.route('/api/v1/admin/aadhaar-login/settings', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def aadhaar_settings(self, **kwargs):
        if not request.env.user.has_group('base.group_system'):
            return api_error('Not authorized.', status=403, code='forbidden')
        return self._settings_response(request.env.user.company_id.sudo())

    @http.route('/api/v1/admin/aadhaar-login/settings', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_aadhaar_settings(self, **kwargs):
        """Any of {"enabled", "otp_enabled", "requires_verified": bool,
        "roles": ["student", "teacher", "parent"], "otp_in_response": bool}.
        otp_in_response is the testing switch (all schools on this server)."""
        if not request.env.user.has_group('base.group_system'):
            return api_error('Not authorized.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        vals = {}
        for key, field_name in SETTING_FIELDS.items():
            if key in payload:
                if not isinstance(payload[key], bool):
                    return api_error(f'{key} must be true or false.', status=400, code=f'invalid_{key}')
                vals[field_name] = payload[key]
        if 'roles' in payload:
            roles = payload['roles']
            if not isinstance(roles, list) or any(role not in ROLES for role in roles):
                return api_error('roles must be a list of student, teacher, parent.', status=400,
                                 code='invalid_roles')
            vals.update({f'bxi_aadhaar_login_allow_{role}': role in roles for role in ROLES})
        if 'otp_in_response' in payload and not isinstance(payload['otp_in_response'], bool):
            return api_error('otp_in_response must be true or false.', status=400, code='invalid_otp_in_response')
        company = request.env.user.company_id.sudo()
        if vals:
            company.write(vals)
        if 'otp_in_response' in payload:
            request.env['ir.config_parameter'].sudo().set_param(
                OTP_IN_RESPONSE_PARAM, 'True' if payload['otp_in_response'] else 'False')
        return self._settings_response(company)
