# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The app's Settings screen: Notification Settings switches and App
Preferences (language, theme, offline mode, auto sync), per login."""
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth

from ..models.student_preferences import NOTIFICATION_SWITCHES, THEMES
from .common import json_body

THEME_KEYS = tuple(key for key, _label in THEMES)


def _languages(env):
    return env['res.lang'].sudo().search([('active', '=', True)], order='name')


def _preferences(user):
    user = user.sudo()
    return {
        'notifications': user._bxi_notification_switches(),
        'app': {
            'language': user.lang,
            'theme': user.bxi_app_theme or 'auto',
            'offline_mode': user.bxi_app_offline_mode,
            'auto_sync': user.bxi_app_auto_sync,
        },
        'languages': [{'code': lang.code, 'name': lang.name} for lang in _languages(user.env)],
        'themes': list(THEME_KEYS),
    }


class BxiApiSupportPreferencesController(http.Controller):

    @http.route('/api/v1/me/preferences', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_preferences(self, **kwargs):
        """The caller's settings. `notifications` switches: assignment
        reminders, exam notifications, grade updates, study reminders - a
        switch that is off stops the phone push; the in-app inbox still
        lists the notification."""
        return api_response(_preferences(request.env.user))

    @http.route('/api/v1/me/preferences', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_preferences(self, **kwargs):
        """Change any of the settings; keys not sent keep their value.
        Body: {"notifications": {"grade_updates": false, ...},
        "app": {"language": "hi_IN", "theme": "dark", "offline_mode": true,
        "auto_sync": false}}."""
        payload = json_body()
        if not isinstance(payload, dict):
            return api_error('Send a JSON object.', status=400, code='invalid_payload')
        notifications = payload.get('notifications') or {}
        app = payload.get('app') or {}
        if not isinstance(notifications, dict) or not isinstance(app, dict):
            return api_error('notifications and app must be objects.', status=400, code='invalid_payload')
        unknown = set(notifications) - set(NOTIFICATION_SWITCHES)
        if unknown:
            return api_error('Unknown notification setting: %s.' % ', '.join(sorted(unknown)),
                             status=400, code='invalid_notification_setting')
        if any(not isinstance(value, bool) for value in notifications.values()):
            return api_error('Notification settings must be true or false.', status=400, code='invalid_value')
        vals = {}
        if 'language' in app:
            if app['language'] not in _languages(request.env).mapped('code'):
                return api_error('This language is not available.', status=400, code='invalid_language')
            vals['lang'] = app['language']
        if 'theme' in app:
            if app['theme'] not in THEME_KEYS:
                return api_error('theme must be one of: %s.' % ', '.join(THEME_KEYS), status=400,
                                 code='invalid_theme')
            vals['bxi_app_theme'] = app['theme']
        for key, field in (('offline_mode', 'bxi_app_offline_mode'), ('auto_sync', 'bxi_app_auto_sync')):
            if key in app:
                if not isinstance(app[key], bool):
                    return api_error('%s must be true or false.' % key, status=400, code='invalid_value')
                vals[field] = app[key]
        user = request.env.user.sudo()
        if vals:
            user.write(vals)
        if notifications:
            user._bxi_set_notification_switches(notifications)
        return api_response(_preferences(user))
