# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from datetime import timedelta

from odoo import api, fields, models

PUSH_BATCH_SIZE = 200
PUSH_MAX_AGE_DAYS = 1


class BxiNotification(models.Model):
    """One in-app inbox entry for one user. Creating it is all a feature
    has to do (via `_notify`): the inbox API reads these rows, and the push
    cron delivers each pending one to the user's registered devices, so a
    slow FCM call never holds up the request that caused the notification.
    """
    _name = 'bxi.notification'
    _description = 'Orbix App Notification'
    _order = 'create_date desc, id desc'

    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade')
    title = fields.Char(required=True)
    body = fields.Text()
    category = fields.Char(
        index=True, help='What caused it, e.g. announcement, message, fee_due, absence - the app '
                         'uses it to pick an icon and the screen to open.')
    res_model = fields.Char(string='Related Model')
    res_id = fields.Integer(string='Related Record ID')
    read_at = fields.Datetime(readonly=True, index=True)
    push_state = fields.Selection([
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('no_device', 'No Device'),
        ('failed', 'Failed'),
        ('disabled', 'Push Disabled'),
    ], default='pending', required=True, index=True)

    @api.model
    def _notify(self, users, title, body=None, category=None, record=None, push=True):
        """Create one inbox entry per user in `users` and queue the push.
        Returns the created notifications. Safe to call with an empty
        recordset or with duplicate users."""
        users = users.filtered('active')
        if not users:
            return self.browse()
        notifications = self.sudo().create([{
            'user_id': user.id,
            'title': title,
            'body': body or False,
            'category': category or False,
            'res_model': record._name if record else False,
            'res_id': record.id if record else False,
            'push_state': 'pending' if push else 'disabled',
        } for user in users])
        if push:
            cron = self.env.ref('bxi_notification_gateway.ir_cron_send_push_notifications', raise_if_not_found=False)
            if cron:
                cron._trigger()
        return notifications

    def _push_payload(self):
        self.ensure_one()
        return {
            'notification_id': self.id,
            'category': self.category,
            'res_model': self.res_model,
            'res_id': self.res_id or None,
        }

    def _send_push(self):
        client = self.env['bxi.fcm.client'].sudo()
        Device = self.env['bxi.api.device'].sudo()
        for notification in self:
            devices = Device.search([('user_id', '=', notification.user_id.id)])
            if not devices:
                notification.push_state = 'no_device'
                continue
            results = []
            for device in devices:
                result = client.send(
                    device.fcm_token, notification.title, notification.body, notification._push_payload())
                if result == 'unregistered':
                    device.active = False
                results.append(result)
            if 'sent' in results:
                notification.push_state = 'sent'
            elif all(r == 'unregistered' for r in results):
                notification.push_state = 'no_device'
            else:
                notification.push_state = 'failed'

    @api.model
    def _cron_send_pending_push(self):
        if not self.env['bxi.fcm.client'].sudo().is_configured():
            return
        # Anything still pending after a day (e.g. FCM was only configured
        # now) is stale - it stays in the inbox but is not pushed late.
        self.sudo().search([
            ('push_state', '=', 'pending'),
            ('create_date', '<', fields.Datetime.now() - timedelta(days=PUSH_MAX_AGE_DAYS)),
        ]).push_state = 'failed'
        pending = self.sudo().search([('push_state', '=', 'pending')], limit=PUSH_BATCH_SIZE, order='id')
        pending._send_push()
        if len(pending) == PUSH_BATCH_SIZE:
            self.env.ref('bxi_notification_gateway.ir_cron_send_push_notifications')._trigger()
