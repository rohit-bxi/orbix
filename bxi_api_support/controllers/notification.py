# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth

from .common import date_str, get_app_student, parse_pagination, json_body

PLATFORMS = ('android', 'ios', 'web')

# The Notifications screen's tabs, by the category each notification is
# created with (bxi_api_support/models/push_triggers.py and the student
# app's notes, doubts and community). Anything else is "system".
TABS = {
    'assignments': ('homework', 'doubt', 'note'),
    'exams': ('exam', 'result'),
    'announcements': ('announcement', 'event', 'ptm', 'community'),
    'achievements': ('certificate', 'achievement'),
}
TAB_NAMES = tuple(TABS) + ('system',)
URGENT = ('absence', 'fee_due', 'security')


def _tab(category):
    return next((tab for tab, categories in TABS.items() if category in categories), 'system')


def _tab_domain(tab):
    if tab == 'system':
        return ['|', ('category', '=', False), ('category', 'not in', [c for cs in TABS.values() for c in cs])]
    return [('category', 'in', list(TABS[tab]))]


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
        'tab': _tab(notification.category),
        'urgent': notification.category in URGENT,
    }


class BxiApiSupportNotificationController(http.Controller):

    @http.route('/api/v1/devices/register', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def register_device(self, **kwargs):
        """Call after every login (and whenever FCM rotates the token)."""
        payload = json_body() or {}
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
        payload = json_body() or {}
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
    def list_notifications(self, unread=None, category=None, tab=None, **kwargs):
        """?tab=assignments|exams|announcements|achievements|system (the
        screen's tabs), ?category=, ?unread=1."""
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [('user_id', '=', request.env.user.id)]
        if unread in ('1', 'true', 'True'):
            domain.append(('read_at', '=', False))
        if category:
            domain.append(('category', '=', category))
        if tab:
            if tab not in TAB_NAMES:
                return api_error('tab must be one of %s.' % ', '.join(TAB_NAMES), status=400, code='invalid_tab')
            domain += _tab_domain(tab)
        Notification = request.env['bxi.notification'].sudo()
        total = Notification.search_count(domain)
        notifications = Notification.search(domain, limit=limit, offset=offset)
        return api_response(
            {'notifications': [_notification_dict(n) for n in notifications]},
            meta={'total': total, 'limit': limit, 'offset': offset,
                  'unread': Notification.search_count([('user_id', '=', request.env.user.id), ('read_at', '=', False)])})

    @http.route('/api/v1/notifications/counts', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def counts(self, student_id=None, **kwargs):
        """The Notifications screen's tab counts and Quick Actions: urgent
        (unread absence / fee / security), achievements (unread), and - for
        a student (or a one-child parent) - homework due within two days
        and homework completed."""
        Notification = request.env['bxi.notification'].sudo()
        mine = [('user_id', '=', request.env.user.id)]
        tabs = {tab: Notification.search_count(mine + _tab_domain(tab)) for tab in TAB_NAMES}
        unread = mine + [('read_at', '=', False)]
        quick = {
            'urgent': Notification.search_count(unread + [('category', 'in', list(URGENT))]),
            'achievements': Notification.search_count(unread + _tab_domain('achievements')),
            'assignments_due_soon': 0,
            'completed_tasks': 0,
        }
        student, error = get_app_student(request.env, student_id)
        if student_id and error:
            return error
        if student:
            from .assignment import _student_tasks
            soon = fields.Datetime.now() + timedelta(days=2)
            tasks = _student_tasks(student)
            quick['assignments_due_soon'] = len([
                1 for a, _sub, status in tasks
                if status in ('due_today', 'upcoming') and a.submission_date and a.submission_date <= soon])
            quick['completed_tasks'] = len([1 for _a, _sub, status in tasks if status == 'completed'])
        return api_response({'all': Notification.search_count(mine), 'unread': Notification.search_count(unread),
                             'tabs': tabs, 'quick_actions': quick})

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
