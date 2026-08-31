# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response


class BxiOtpController(http.Controller):

    @http.route('/api/v1/otp/request', type='http', auth='public', methods=['POST'], csrf=False)
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
