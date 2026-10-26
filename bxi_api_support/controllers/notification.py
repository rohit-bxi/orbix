# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth

from .common import date_str, parse_pagination

PLATFORMS = ('android', 'ios', 'web')


def _notification_dict(notification):
    return {
        'id': notification.id,
        'title': notification.title,
        'body': notification.body or None,
        'category': notification.category or None,
        'res_model': notification.res_model or None,
        'res_id': notification.res_id or None,
        'created_at': date_str(notification.create_date),
        'read_at': date_str(notification.read_at),
        'is_read': bool(notification.read_at),
    }


class BxiApiSupportNotificationController(http.Controller):

    @http.route('/api/v1/devices/register', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def register_device(self, **kwargs):
        """Call after every login (and whenever FCM rotates the token)."""
        payload = request.get_json_data() or {}
        fcm_token = (payload.get('fcm_token') or '').strip()
        platform = payload.get('platform') or 'android'
        if not fcm_token:
            return api_error('fcm_token is required.', status=400, code='missing_fcm_token')
        if platform not in PLATFORMS:
            return api_error('platform must be one of %s.' % ', '.join(PLATFORMS), status=400, code='invalid_platform')
        device = request.env['bxi.api.device']._register_device(
            request.env.user, fcm_token, platform=platform,
            device_name=payload.get('device_name'), app_version=payload.get('app_version'))
        return api_response({'device_id': device.id, 'registered': True})

    @http.route('/api/v1/devices/unregister', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def unregister_device(self, **kwargs):
        """Call on logout so the phone stops receiving this user's pushes."""
        payload = request.get_json_data() or {}
        fcm_token = (payload.get('fcm_token') or '').strip()
        if not fcm_token:
            return api_error('fcm_token is required.', status=400, code='missing_fcm_token')
        devices = request.env['bxi.api.device'].sudo().search([
            ('fcm_token', '=', fcm_token), ('user_id', '=', request.env.user.id),
        ])
        devices.write({'active': False})
        return api_response({'unregistered': bool(devices)})

    @http.route('/api/v1/notifications', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_notifications(self, unread=None, category=None, **kwargs):
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [('user_id', '=', request.env.user.id)]
        if unread in ('1', 'true', 'True'):
            domain.append(('read_at', '=', False))
        if category:
            domain.append(('category', '=', category))
        Notification = request.env['bxi.notification'].sudo()
        total = Notification.search_count(domain)
        notifications = Notification.search(domain, limit=limit, offset=offset)
        return api_response(
            {'notifications': [_notification_dict(n) for n in notifications]},
            meta={'total': total, 'limit': limit, 'offset': offset,
                  'unread': Notification.search_count([('user_id', '=', request.env.user.id), ('read_at', '=', False)])})

    @http.route('/api/v1/notifications/unread-count', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def unread_count(self, **kwargs):
        count = request.env['bxi.notification'].sudo().search_count([
            ('user_id', '=', request.env.user.id), ('read_at', '=', False),
        ])
        return api_response({'unread': count})

    @http.route('/api/v1/notifications/<int:notification_id>/read', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def mark_read(self, notification_id, **kwargs):
        notification = request.env['bxi.notification'].sudo().browse(notification_id)
        if not notification.exists() or notification.user_id != request.env.user:
            return api_error('Notification not found.', status=404, code='not_found')
        if not notification.read_at:
            notification.read_at = fields.Datetime.now()
        return api_response(_notification_dict(notification))

    @http.route('/api/v1/notifications/read-all', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def mark_all_read(self, **kwargs):
        unread = request.env['bxi.notification'].sudo().search([
            ('user_id', '=', request.env.user.id), ('read_at', '=', False),
        ])
        unread.write({'read_at': fields.Datetime.now()})
        return api_response({'marked_read': len(unread)})
