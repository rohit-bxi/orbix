# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Aadhaar login on the website login page (/web/login) and a two-step
emailed-code login page (/web/login/aadhaar-code)."""
import time

from odoo import _, http
from odoo.exceptions import AccessDenied
from odoo.http import request

from odoo.addons.bxi_api.controllers import auth as api_auth
from odoo.addons.bxi_identity_verification.models.aadhaar import (
    clean_aadhaar, looks_like_aadhaar, normalize_aadhaar,
)
from odoo.addons.web.controllers.home import Home
from odoo.addons.web.controllers.utils import ensure_db

from ..models.res_users import EMAIL_OTP_CREDENTIAL, EmailOtpDenied, mask_email

SESSION_KEY = 'bxi_aadhaar_code_login'


def _web_rate_ok(bucket, limit, window=60):
    """The API rate limiter (bxi_api), for HTML forms: False when this IP
    made `limit` calls to `bucket` in the last `window` seconds."""
    if not api_auth._rate_limit_active():
        return True
    calls = api_auth._rate_buckets[(bucket, request.httprequest.remote_addr)]
    now = time.monotonic()
    while calls and now - calls[0] > window:
        calls.popleft()
    if len(calls) >= limit:
        return False
    calls.append(now)
    return True


def _aadhaar_flags():
    companies = request.env['res.company'].sudo().search([('bxi_aadhaar_login_enabled', '=', True)])
    return {
        'bxi_aadhaar_login': bool(companies),
        'bxi_aadhaar_otp': any(companies.mapped('bxi_aadhaar_login_otp_enabled')),
    }


class BxiAadhaarHome(Home):

    @http.route()
    def web_login(self, redirect=None, **kw):
        """The login box also takes an Aadhaar number: it is swapped for
        the account's username before Odoo checks the password (Odoo logs
        the login it is given - never the Aadhaar number), and put back in
        the form if the login fails."""
        typed, ambiguous = None, False
        if request.httprequest.method == 'POST':
            ensure_db()
            typed, ambiguous = self._bxi_swap_aadhaar_login()
        response = super().web_login(redirect=redirect, **kw)
        qcontext = getattr(response, 'qcontext', None)
        if qcontext is not None:
            qcontext.update(_aadhaar_flags())
            if typed:
                qcontext['login'] = typed
                if ambiguous and qcontext.get('error'):
                    qcontext['error'] = _('This Aadhaar number is linked to more than one account. '
                                          'Please log in with your username.')
        return response

    @staticmethod
    def _bxi_swap_aadhaar_login():
        """(typed Aadhaar or None, ambiguous). Replaces request.params
        ['login'] when it is an Aadhaar number and not a real username."""
        login = request.params.get('login')
        if not looks_like_aadhaar(login):
            return None, False
        Users = request.env['res.users'].sudo().with_context(active_test=False)
        if Users.search_count([('login', 'in', list({login.strip(), clean_aadhaar(login.strip())}))]):
            return None, False
        if not _aadhaar_flags()['bxi_aadhaar_login']:
            return None, False
        user, _records, reason = Users._bxi_aadhaar_resolve(login)
        # A placeholder that matches no account, so the failure is logged
        # without the number.
        request.params['login'] = user.login if user else 'aadhaar-XXXXXXXX%s' % normalize_aadhaar(login)[-4:]
        return login, reason == 'ambiguous'

    @http.route('/web/login/aadhaar-code', type='http', auth='public', methods=['GET', 'POST'], website=True,
                sitemap=False)
    def aadhaar_code_login(self, redirect=None, **kw):
        """Step 1 ("step": "request"): Aadhaar number -> a code is emailed
        to the address on the school record. Step 2 ("step": "verify"): the
        code signs in. Which account the code is for stays in the session;
        an unknown number gets the same screens and a code that never works."""
        if request.session.uid:
            return request.redirect(self._login_redirect(request.session.uid, redirect=redirect))
        flags = _aadhaar_flags()
        values = {'redirect': redirect, 'stage': 'aadhaar', 'error': None, 'aadhaar': ''}
        if not flags['bxi_aadhaar_otp']:
            values['error'] = _('Logging in with an emailed code is not available.')
            return self._render_code_page(values)
        if request.httprequest.method == 'POST':
            step = kw.get('step')
            if step == 'request':
                self._code_request(kw.get('aadhaar') or '', values)
            elif step == 'verify':
                response = self._code_verify(kw.get('otp') or '', redirect, values)
                if response:
                    return response
        return self._render_code_page(values)

    @staticmethod
    def _render_code_page(values):
        response = request.render('bxi_aadhaar_login.aadhaar_code_login', values)
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response

    @staticmethod
    def _code_request(number, values):
        values['aadhaar'] = number
        if not normalize_aadhaar(number):
            values['error'] = _('Enter a valid 12-digit Aadhaar number.')
            return
        if not _web_rate_ok('aadhaar_otp_request', 5):
            values['error'] = _('Too many requests. Please wait a minute and try again.')
            return
        Users = request.env['res.users'].sudo()
        user, records, reason = Users._bxi_aadhaar_resolve(number)
        if reason == 'ambiguous':
            values['error'] = _('This Aadhaar number is linked to more than one account. '
                                'Please log in with your username.')
            return
        hint, uid = Users._bxi_fake_email_hint(number), False
        if user and user.company_id.bxi_aadhaar_login_otp_enabled:
            email = user._bxi_aadhaar_otp_email(records)
            if email:
                request.env['bxi.otp.request'].sudo()._generate_and_email(user, email, purpose='login')
                hint, uid = mask_email(email), user.id
        request.session[SESSION_KEY] = {'uid': uid, 'hint': hint}
        values.update(stage='code', email_hint=hint, aadhaar='')

    def _code_verify(self, code, redirect, values):
        state = request.session.get(SESSION_KEY)
        if not state:
            values['error'] = _('Please enter your Aadhaar number again.')
            return None
        values.update(stage='code', email_hint=state.get('hint'))
        code = code.strip()
        if not _web_rate_ok('aadhaar_otp_login', 10):
            values['error'] = _('Too many attempts. Please wait a minute and try again.')
            return None
        user = request.env['res.users'].sudo().browse(state.get('uid') or [])
        if not user or not code:
            values['error'] = _('The code is not correct.')
            return None
        try:
            auth_info = request.session.authenticate(
                request.env, {'type': EMAIL_OTP_CREDENTIAL, 'login': user.login, 'otp': code})
        except EmailOtpDenied as exc:
            values['error'] = exc.args[0]
            if exc.reason in ('expired', 'too_many_attempts', 'not_found'):
                request.session.pop(SESSION_KEY, None)
                values['stage'] = 'aadhaar'
            return None
        except AccessDenied:
            values['error'] = _('The code could not be checked. Please wait a moment and try again.')
            return None
        request.session.pop(SESSION_KEY, None)
        return request.redirect(self._login_redirect(auth_info['uid'], redirect=redirect))
