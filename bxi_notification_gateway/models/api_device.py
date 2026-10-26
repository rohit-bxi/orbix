# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import api, fields, models


class BxiApiDevice(models.Model):
    """A phone/tablet that can receive push notifications for a user. One
    row per FCM registration token - the app registers after login and
    unregisters on logout; tokens FCM reports as dead are deactivated by
    the push cron.
    """
    _name = 'bxi.api.device'
    _description = 'Orbix App Device'
    _order = 'last_seen_at desc, id desc'

    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade')
    fcm_token = fields.Char(string='FCM Token', required=True, index=True, copy=False)
    platform = fields.Selection([
        ('android', 'Android'),
        ('ios', 'iOS'),
        ('web', 'Web'),
    ], required=True, default='android')
    device_name = fields.Char()
    app_version = fields.Char()
    last_seen_at = fields.Datetime(readonly=True)
    active = fields.Boolean(default=True)

    _fcm_token_unique = models.Constraint('unique(fcm_token)', 'This device token is already registered.')

    @api.model
    def _register_device(self, user, fcm_token, platform='android', device_name=None, app_version=None):
        """Upsert by token. A token already registered to someone else is
        moved to `user` - the same phone logged in with another account -
        so pushes never reach the previous account's owner."""
        vals = {
            'user_id': user.id,
            'platform': platform,
            'device_name': device_name or False,
            'app_version': app_version or False,
            'last_seen_at': fields.Datetime.now(),
            'active': True,
        }
        device = self.sudo().with_context(active_test=False).search([('fcm_token', '=', fcm_token)], limit=1)
        if device:
            device.write(vals)
        else:
            device = self.sudo().create(dict(vals, fcm_token=fcm_token))
        return device
