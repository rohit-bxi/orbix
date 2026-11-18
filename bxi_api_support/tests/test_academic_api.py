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

    def test_reset_curriculum_to_draft(self):
        headers = self._headers('academic_api_coordinator', 'CoordPass1!')
        self.url_open(f'/api/v1/academic/curricula/{self.curriculum.id}/approve', headers=headers, method='POST')
        url = f'/api/v1/academic/curricula/{self.curriculum.id}/reset'
        self.assertEqual(self.url_open(url, headers=self._headers('academic_api_other', 'OtherPass1!'),
                                       method='POST').status_code, 403)
        reset = self.url_open(url, headers=headers, method='POST')
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(reset.json()['data']['approval_status'], 'draft')
        self.assertEqual(self.url_open('/api/v1/academic/curricula/999999/reset', headers=headers,
                                       method='POST').status_code, 404)

    def test_subject_mappings_filters(self):
        course_a = self.env['op.course'].create({'name': 'Map Class A', 'code': 'MAP-A'})
        course_b = self.env['op.course'].create({'name': 'Map Class B', 'code': 'MAP-B'})
        subject = self.env['op.subject'].create({'name': 'Map Science', 'code': 'MAP-S'})
        teacher_a = self.env['op.faculty'].create({
            'first_name': 'Map', 'last_name': 'Alpha', 'gender': 'female', 'birth_date': '1985-01-01'})
        teacher_b = self.env['op.faculty'].create({
            'first_name': 'Map', 'last_name': 'Beta', 'gender': 'male', 'birth_date': '1985-01-01'})
        Mapping = self.env['bxi.subject.mapping']
        first = Mapping.create({'subject_id': subject.id, 'class_id': course_a.id, 'teacher_id': teacher_a.id,
                                'curriculum_id': self.curriculum.id})
        second = Mapping.create({'subject_id': subject.id, 'class_id': course_b.id, 'teacher_id': teacher_b.id,
                                 'curriculum_id': self.curriculum.id})
        headers = self._headers('academic_api_coordinator', 'CoordPass1!')
        by_class = self.url_open(f'/api/v1/academic/subject-mappings?class_id={course_a.id}', headers=headers)
        self.assertEqual(by_class.status_code, 200, by_class.text)
        self.assertEqual([m['id'] for m in by_class.json()['data']['mappings']], [first.id])
        self.assertEqual(by_class.json()['data']['mappings'][0]['teacher'], teacher_a.display_name)
        by_teacher = self.url_open(f'/api/v1/academic/subject-mappings?teacher_id={teacher_b.id}', headers=headers).json()
        self.assertEqual([m['id'] for m in by_teacher['data']['mappings']], [second.id])
        self.assertEqual(by_teacher['meta']['total'], 1)
        mail_new_test_user(self.env, login='academic_api_parent', groups='base.group_portal', password='ParentPass1!')
        self.assertEqual(self.url_open('/api/v1/academic/subject-mappings',
                                       headers=self._headers('academic_api_parent', 'ParentPass1!')).status_code, 403)

    def test_curricula_list_and_detail(self):
        headers = self._headers('academic_api_coordinator', 'CoordPass1!')
        listing = self.url_open('/api/v1/academic/curricula', headers=headers)
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertIn(self.curriculum.id, [c['id'] for c in listing.json()['data']['curricula']])
        detail = self.url_open(f'/api/v1/academic/curricula/{self.curriculum.id}', headers=headers)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['data']['name'], 'API Curriculum')
