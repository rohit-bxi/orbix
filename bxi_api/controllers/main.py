# -*- coding: utf-8 -*-

from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request

from .auth import api_error, api_response, require_auth


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
        raw_token = request.env['bxi.api.token']._issue_for_user(user, name=payload.get('device_name'))
        return api_response({
            'token': raw_token,
            'user': {
                'id': user.id,
                'name': user.name,
                'login': user.login,
                'email': user.email,
            },
        })

    @http.route('/api/v1/auth/logout', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def logout(self, **kwargs):
        auth_header = request.httprequest.headers.get('Authorization', '')
        raw_token = auth_header[7:] if auth_header.startswith('Bearer ') else None
        Token = request.env['bxi.api.token'].sudo()
        token = Token.search([('token_hash', '=', Token._hash(raw_token))], limit=1)
        if token:
            token.action_revoke()
        return api_response({'logged_out': True})

    @http.route('/api/v1/auth/me', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def me(self, **kwargs):
        user = request.env.user
        return api_response({
            'id': user.id,
            'name': user.name,
            'login': user.login,
            'email': user.email,
        })
