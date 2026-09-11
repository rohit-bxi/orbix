# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportNotice(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager_user = mail_new_test_user(
            cls.env, login='notice_api_manager',
            groups='base.group_user,bxi_school_notice.group_notice_manager',
            password='ManagerPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='notice_api_other', groups='base.group_user', password='OtherPass1!')

    def _manager_headers(self):
        return self._headers('notice_api_manager', 'ManagerPass1!')

    def test_notices_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/notices').status_code, 401)

    def test_non_manager_cannot_post_notice(self):
        resp = self.url_open('/api/v1/notices', headers=self._headers('notice_api_other', 'OtherPass1!'), json={
            'title': 'Test', 'body': 'Body',
        })
        self.assertEqual(resp.status_code, 403)

    def test_create_notice_is_immediately_visible(self):
        headers = self._manager_headers()
        create = self.url_open('/api/v1/notices', headers=headers, json={
            'title': 'Holiday Notice', 'body': 'School closed Friday.', 'category': 'holiday',
        })
        self.assertEqual(create.status_code, 201)
        notice_id = create.json()['data']['id']

        other_headers = self._headers('notice_api_other', 'OtherPass1!')
        listing = self.url_open('/api/v1/notices', headers=other_headers).json()['data']['notices']
        self.assertIn(notice_id, [n['id'] for n in listing])

    def test_toggle_pin(self):
        headers = self._manager_headers()
        create = self.url_open('/api/v1/notices', headers=headers, json={'title': 'Pin Me', 'body': 'Body'})
        notice_id = create.json()['data']['id']
        self.assertFalse(create.json()['data']['is_pinned'])

        toggle = self.url_open(f'/api/v1/notices/{notice_id}/toggle-pin', headers=headers, method='POST')
        self.assertEqual(toggle.status_code, 200)
        self.assertTrue(toggle.json()['data']['is_pinned'])

    def test_update_notice(self):
        headers = self._manager_headers()
        create = self.url_open('/api/v1/notices', headers=headers, json={'title': 'Old Title', 'body': 'Body'})
        notice_id = create.json()['data']['id']

        update = self.url_open(f'/api/v1/notices/{notice_id}/update', headers=headers, json={'title': 'New Title'})
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.json()['data']['title'], 'New Title')

    def test_create_notice_missing_body_rejected(self):
        resp = self.url_open('/api/v1/notices', headers=self._manager_headers(), json={'title': 'No body'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_body')
