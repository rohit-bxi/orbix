# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, http
from odoo.exceptions import AccessDenied, UserError
from odoo.http import request

from .auth import api_error, api_response, get_current_token, require_auth


def _token_dict(token, current):
    return {
        'id': token.id,
        'name': token.name,
        'token_last4': token.token_last4,
        'created_at': fields.Datetime.to_string(token.create_date),
        'last_used_at': token.last_used_at and fields.Datetime.to_string(token.last_used_at),
        'expires_at': token.expires_at and fields.Datetime.to_string(token.expires_at),
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
    def _issue_login_response(user, device_name=None):
        """Shared by password login and OTP login (bxi_notification_gateway)
        so both hand back exactly the same shape."""
        raw_token = request.env['bxi.api.token']._issue_for_user(user, name=device_name)
        return {
            'token': raw_token,
            'user': user._get_bxi_api_profile(),
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
    def revoke_session(self, session_id, **kwargs):
        token = request.env['bxi.api.token'].sudo().browse(session_id)
        if not token.exists() or token.user_id.id != request.env.user.id:
            return api_error('Session not found.', status=404, code='not_found')
        token.action_revoke()
        return api_response({'revoked': True, 'id': session_id})

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
