# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportAnnouncement(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager_user = mail_new_test_user(
            cls.env, login='ann_api_manager',
            groups='base.group_user,bxi_school_announcement.group_announcement_manager',
            password='ManagerPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='ann_api_other', groups='base.group_user', password='OtherPass1!')

    def _manager_headers(self):
        return self._headers('ann_api_manager', 'ManagerPass1!')

    def test_announcements_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/announcements').status_code, 401)

    def test_non_manager_cannot_create(self):
        resp = self.url_open('/api/v1/announcements', headers=self._headers('ann_api_other', 'OtherPass1!'), json={
            'title': 'Test', 'body': 'Body',
        })
        self.assertEqual(resp.status_code, 403)

    def test_manager_create_publish_archive_flow(self):
        headers = self._manager_headers()
        create = self.url_open('/api/v1/announcements', headers=headers, json={
            'title': 'School Reopens', 'body': 'School reopens Monday.', 'category': 'general',
        })
        self.assertEqual(create.status_code, 201)
        self.assertEqual(create.json()['data']['state'], 'draft')
        ann_id = create.json()['data']['id']

        publish = self.url_open(f'/api/v1/announcements/{ann_id}/publish', headers=headers, method='POST')
        self.assertEqual(publish.status_code, 200)
        self.assertEqual(publish.json()['data']['state'], 'published')

        archive = self.url_open(f'/api/v1/announcements/{ann_id}/archive', headers=headers, method='POST')
        self.assertEqual(archive.status_code, 200)
        self.assertEqual(archive.json()['data']['state'], 'archived')

    def test_any_authenticated_user_reads_published_only(self):
        headers = self._manager_headers()
        create = self.url_open('/api/v1/announcements', headers=headers, json={
            'title': 'Draft Only', 'body': 'Should not be visible to non-managers.',
        })
        ann_id = create.json()['data']['id']

        other_headers = self._headers('ann_api_other', 'OtherPass1!')
        listing = self.url_open('/api/v1/announcements', headers=other_headers).json()['data']['announcements']
        self.assertNotIn(ann_id, [a['id'] for a in listing])

        self.url_open(f'/api/v1/announcements/{ann_id}/publish', headers=headers, method='POST')
        listing_after = self.url_open('/api/v1/announcements', headers=other_headers).json()['data']['announcements']
        self.assertIn(ann_id, [a['id'] for a in listing_after])

    def test_create_missing_body_rejected(self):
        resp = self.url_open('/api/v1/announcements', headers=self._manager_headers(), json={'title': 'No body'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_body')
