# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportAcademic(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coordinator_user = mail_new_test_user(
            cls.env, login='academic_api_coordinator',
            groups='base.group_user,bxi_academic_management.group_academic_coordinator',
            password='CoordPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='academic_api_other', groups='base.group_user', password='OtherPass1!')
        cls.board = cls.env['bxi.board'].create({'name': 'API Board'})
        cls.curriculum = cls.env['bxi.curriculum'].create({
            'name': 'API Curriculum', 'board_id': cls.board.id, 'description': 'Test curriculum.',
        })

    def test_curricula_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/academic/curricula').status_code, 401)

    def test_non_coordinator_cannot_approve(self):
        resp = self.url_open(
            f'/api/v1/academic/curricula/{self.curriculum.id}/approve',
            headers=self._headers('academic_api_other', 'OtherPass1!'), method='POST')
        self.assertEqual(resp.status_code, 403)

    def test_coordinator_approval_lifecycle(self):
        headers = self._headers('academic_api_coordinator', 'CoordPass1!')
        approve = self.url_open(
            f'/api/v1/academic/curricula/{self.curriculum.id}/approve', headers=headers, method='POST')
        self.assertEqual(approve.status_code, 200)
        self.assertEqual(approve.json()['data']['approval_status'], 'approved')

        lock = self.url_open(
            f'/api/v1/academic/curricula/{self.curriculum.id}/toggle-lock', headers=headers, method='POST')
        self.assertEqual(lock.status_code, 200)
        self.assertTrue(lock.json()['data']['locked'])

        reject = self.url_open(
            f'/api/v1/academic/curricula/{self.curriculum.id}/reject', headers=headers, method='POST')
        self.assertEqual(reject.status_code, 200)
        self.assertEqual(reject.json()['data']['approval_status'], 'rejected')

    def test_curriculum_not_found(self):
        resp = self.url_open(
            '/api/v1/academic/curricula/999999', headers=self._headers('academic_api_coordinator', 'CoordPass1!'))
        self.assertEqual(resp.status_code, 404)
