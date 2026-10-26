# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.bxi_notification_gateway.models.fcm_client import FcmClient

SENT = []


def _fake_send(results):
    def send(self, device_token, title, body, data=None):
        SENT.append({'token': device_token, 'title': title, 'data': data})
        return results.get(device_token, 'sent')
    return send


@tagged('post_install', '-at_install')
class TestBxiPush(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'Push User', 'login': 'push_user', 'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.other = cls.env['res.users'].create({
            'name': 'Push Other', 'login': 'push_other', 'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param('bxi_notification_gateway.fcm_project_id', 'orbix-test')
        ICP.set_param('bxi_notification_gateway.fcm_service_account_json', '{}')

    def setUp(self):
        super().setUp()
        SENT.clear()

    def test_register_moves_token_to_new_user(self):
        Device = self.env['bxi.api.device']
        first = Device._register_device(self.user, 'tok-shared', platform='ios')
        second = Device._register_device(self.other, 'tok-shared', platform='android')
        self.assertEqual(first, second)
        self.assertEqual(second.user_id, self.other)
        self.assertEqual(Device.search_count([('fcm_token', '=', 'tok-shared')]), 1)

    def test_notify_creates_inbox_rows_and_cron_pushes(self):
        self.env['bxi.api.device']._register_device(self.user, 'tok-user')
        notifications = self.env['bxi.notification']._notify(
            self.user | self.other, 'Hello', 'Body', category='announcement', record=self.user)
        self.assertEqual(len(notifications), 2)
        with patch.object(FcmClient, 'send', _fake_send({})):
            self.env['bxi.notification']._cron_send_pending_push()
        by_user = {n.user_id: n for n in notifications}
        self.assertEqual(by_user[self.user].push_state, 'sent')
        self.assertEqual(by_user[self.other].push_state, 'no_device')
        self.assertEqual(SENT[0]['data']['res_model'], 'res.users')
        self.assertEqual(SENT[0]['data']['notification_id'], by_user[self.user].id)

    def test_unregistered_token_deactivates_device(self):
        device = self.env['bxi.api.device']._register_device(self.user, 'tok-dead')
        notification = self.env['bxi.notification']._notify(self.user, 'Hi')
        with patch.object(FcmClient, 'send', _fake_send({'tok-dead': 'unregistered'})):
            self.env['bxi.notification']._cron_send_pending_push()
        self.assertFalse(device.active)
        self.assertEqual(notification.push_state, 'no_device')

    def test_push_disabled_rows_are_never_sent(self):
        self.env['bxi.api.device']._register_device(self.user, 'tok-user')
        notification = self.env['bxi.notification']._notify(self.user, 'Inbox only', push=False)
        with patch.object(FcmClient, 'send', _fake_send({})):
            self.env['bxi.notification']._cron_send_pending_push()
        self.assertEqual(notification.push_state, 'disabled')
        self.assertFalse(SENT)

    def test_stale_pending_rows_are_not_pushed_late(self):
        self.env['bxi.api.device']._register_device(self.user, 'tok-user')
        notification = self.env['bxi.notification']._notify(self.user, 'Old news')
        self.env.cr.execute(
            'UPDATE bxi_notification SET create_date = %s WHERE id = %s',
            [fields.Datetime.now() - timedelta(days=3), notification.id])
        notification.invalidate_recordset(['create_date'])
        with patch.object(FcmClient, 'send', _fake_send({})):
            self.env['bxi.notification']._cron_send_pending_push()
        self.assertEqual(notification.push_state, 'failed')
        self.assertFalse(SENT)

    def test_cron_does_nothing_when_fcm_not_configured(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_notification_gateway.fcm_project_id', '')
        notification = self.env['bxi.notification']._notify(self.user, 'Waiting')
        with patch.object(FcmClient, 'send', _fake_send({})):
            self.env['bxi.notification']._cron_send_pending_push()
        self.assertEqual(notification.push_state, 'pending')
