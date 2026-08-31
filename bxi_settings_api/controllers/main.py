# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth

# group -> {field_name: (config_parameter key, is_secret)}
SETTINGS_REGISTRY = {
    'notifications': {
        'msg91_auth_key': ('bxi_notification_gateway.msg91_auth_key', True),
        'msg91_sender_id': ('bxi_notification_gateway.msg91_sender_id', False),
        'msg91_otp_template_id': ('bxi_notification_gateway.msg91_otp_template_id', False),
    },
    'finance': {
        'razorpay_key_id': ('bxi_online_fee_payment.razorpay_key_id', False),
        'razorpay_key_secret': ('bxi_online_fee_payment.razorpay_key_secret', True),
        'razorpay_webhook_secret': ('bxi_online_fee_payment.razorpay_webhook_secret', True),
        'online_payment_journal_id': ('bxi_online_fee_payment.default_journal_id', False),
    },
}


class BxiSettingsApiController(http.Controller):

    @http.route('/api/v1/admin/settings', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_settings(self, **kwargs):
        if not request.env.user.has_group('base.group_system'):
            return api_error('Not authorized. Full administration access is required.', status=403, code='forbidden')

        ICP = request.env['ir.config_parameter'].sudo()
        result = {}
        for group, fields_map in SETTINGS_REGISTRY.items():
            result[group] = {}
            for field_name, (key, is_secret) in fields_map.items():
                value = ICP.get_param(key)
                result[group][field_name] = {'configured': bool(value)} if is_secret else value
        return api_response(result)

    @http.route('/api/v1/admin/settings', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_settings(self, **kwargs):
        if not request.env.user.has_group('base.group_system'):
            return api_error('Not authorized. Full administration access is required.', status=403, code='forbidden')

        payload = request.get_json_data()
        ICP = request.env['ir.config_parameter'].sudo()
        updated = []
        for group, fields_map in payload.items():
            if group not in SETTINGS_REGISTRY or not isinstance(fields_map, dict):
                return api_error(f"Unknown settings group '{group}'.", status=400, code='invalid_group')
            for field_name, value in fields_map.items():
                if field_name not in SETTINGS_REGISTRY[group]:
                    return api_error(f"Unknown setting '{field_name}' in group '{group}'.", status=400, code='invalid_field')
                key, _is_secret = SETTINGS_REGISTRY[group][field_name]
                ICP.set_param(key, value if value is not None else '')
                updated.append(f'{group}.{field_name}')

        return api_response({'updated': updated})
