# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, http
from odoo.exceptions import AccessDenied, UserError
from odoo.http import request

from .auth import api_error, api_response, get_current_token, rate_limit, require_auth, require_step_up


def _token_dict(token, current):
    return {
        'id': token.id,
        'name': token.name,
        'token_last4': token.token_last4,
        'created_at': fields.Datetime.to_string(token.create_date),
        'last_used_at': token.last_used_at and fields.Datetime.to_string(token.last_used_at),
        'expires_at': token.expires_at and fields.Datetime.to_string(token.expires_at),
        'auth_method': token.auth_method,
        'is_current': token.id == current.id,
    }


class BxiApiAuthController(http.Controller):

    @http.route('/api/v1/auth/login', type='http', auth='public', methods=['POST'], csrf=False)
    def login(self, **kwargs):
        payload = request.get_json_data()
        login = (payload.get('login') or '').strip()
        password = payload.get('password') or ''
        if not login or not password:
            return api_error('login and password are required.', status=400, code='missing_credentials')

        try:
            auth_info = request.env['res.users'].sudo().authenticate(
                {'type': 'password', 'login': login, 'password': password},
                {'interactive': False},
            )
        except AccessDenied:
            return api_error('Invalid login or password.', status=401, code='invalid_credentials')

        user = request.env['res.users'].sudo().browse(auth_info['uid'])
        return api_response(self._issue_login_response(user, payload.get('device_name')))

    @staticmethod
    def _issue_login_response(user, device_name=None, auth_method='password', **token_options):
        """Shared by password, OTP (bxi_notification_gateway) and face
        (bxi_face_auth) login so all hand back exactly the same shape.
        `token_options` go to bxi.api.token._issue_for_user (ttl_days,
        ttl_minutes, step_up_required)."""
        raw_token = request.env['bxi.api.token']._issue_for_user(
            user, name=device_name, auth_method=auth_method, **token_options)
        return {
            'token': raw_token,
            'user': user._get_bxi_api_profile(),
            'auth_method': auth_method,
        }

    @http.route('/api/v1/auth/logout', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def logout(self, **kwargs):
        token = get_current_token()
        if token:
            token.action_revoke()
        return api_response({'logged_out': True})

    @http.route('/api/v1/auth/me', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def me(self, **kwargs):
        return api_response(request.env.user._get_bxi_api_profile())

    @http.route('/api/v1/auth/sessions', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_sessions(self, **kwargs):
        current = get_current_token()
        tokens = request.env['bxi.api.token'].sudo().search([
            ('user_id', '=', request.env.user.id), ('active', '=', True),
        ])
        now = fields.Datetime.now()
        tokens = tokens.filtered(lambda t: not t.expires_at or t.expires_at >= now)
        return api_response({'sessions': [_token_dict(t, current) for t in tokens]})

    @http.route('/api/v1/auth/sessions/<int:session_id>/revoke', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @require_step_up
    def revoke_session(self, session_id, **kwargs):
        token = request.env['bxi.api.token'].sudo().browse(session_id)
        if not token.exists() or token.user_id.id != request.env.user.id:
            return api_error('Session not found.', status=404, code='not_found')
        token.action_revoke()
        return api_response({'revoked': True, 'id': session_id})

    @http.route('/api/v1/auth/step-up', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('step_up', limit=10)
    @require_auth
    def step_up(self, **kwargs):
        """Confirm the password (or, with bxi_notification_gateway, an OTP
        from /api/v1/auth/step-up/otp-request) on the current session, so
        routes guarded by require_step_up/require_recent_auth accept it for
        the next few minutes."""
        payload = request.get_json_data() or {}
        ok, code = request.env.user._bxi_check_step_up(payload)
        if not ok:
            status = 400 if code == 'missing_credentials' else 401
            return api_error('Confirmation failed.', status=status, code=code)
        token = get_current_token()
        token._mark_verified()
        return api_response({
            'verified': True,
            'verified_until': fields.Datetime.to_string(token.verified_until),
        })

    @http.route('/api/v1/auth/password/change', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def change_password(self, **kwargs):
        payload = request.get_json_data() or {}
        old_password = payload.get('old_password') or ''
        new_password = payload.get('new_password') or ''
        if not old_password or not new_password:
            return api_error('old_password and new_password are required.', status=400, code='missing_fields')
        try:
            request.env['res.users'].change_password(old_password, new_password)
        except AccessDenied:
            return api_error('Current password is incorrect.', status=400, code='invalid_old_password')
        except UserError as exc:
            return api_error(str(exc), status=400, code='invalid_password')
        # Every other device has to log in again with the new password.
        request.env['bxi.api.token']._revoke_all_for_user(request.env.user, keep=get_current_token())
        return api_response({'changed': True})
