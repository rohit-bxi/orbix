# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64

from odoo.tests import HttpCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user

# Smallest valid PDF the mimetype sniffer recognises.
PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'


@tagged('post_install', '-at_install')
class TestBxiElearningApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student_user = mail_new_test_user(
            cls.env, login='elapi_student', password='StudentPass1!', groups='base.group_portal')
        cls.other_user = mail_new_test_user(
            cls.env, login='elapi_other', password='OtherPass1!', groups='base.group_portal')
        cls.grade = cls.env['elearning.class'].create({'name': 'ElApi Grade 6'})
        cls.section = cls.env['elearning.section'].create({'name': 'ElApi 6A', 'class_id': cls.grade.id})
        cls.other_grade = cls.env['elearning.class'].create({'name': 'ElApi Grade 7'})
        cls.course = cls.env['slide.channel'].create({
            'name': 'ElApi Fractions', 'class_id': cls.grade.id, 'section_id': cls.section.id,
            'enroll': 'public', 'visibility': 'connected', 'is_published': True,
        })
        cls.chapter = cls.env['slide.slide'].create({
            'name': 'ElApi Basics', 'channel_id': cls.course.id, 'is_category': True, 'sequence': 1,
            'is_published': True,
        })
        cls.article = cls.env['slide.slide'].create({
            'name': 'ElApi What is a fraction', 'channel_id': cls.course.id, 'slide_category': 'article',
            'html_content': '<p>Half</p>', 'is_published': True, 'sequence': 2,
        })
        cls.pdf = cls.env['slide.slide'].create({
            'name': 'ElApi Worksheet', 'channel_id': cls.course.id, 'slide_category': 'document',
            'binary_content': base64.b64encode(PDF), 'is_published': True, 'sequence': 3, 'is_preview': True,
        })
        cls.invite_only = cls.env['slide.channel'].create({
            'name': 'ElApi Olympiad', 'class_id': cls.other_grade.id, 'enroll': 'invite', 'visibility': 'members',
            'is_published': True,
        })
        cls.draft = cls.env['slide.channel'].create({'name': 'ElApi Draft', 'class_id': cls.grade.id,
                                                     'is_published': False})

    def _headers(self, login='elapi_student', password='StudentPass1!'):
        resp = self.url_open('/api/v1/auth/login', json={'login': login, 'password': password})
        return {'Authorization': f'Bearer {resp.json()["data"]["token"]}'}

    def _post(self, path, headers=None):
        return self.url_open(path, headers=headers or self._headers(), json={}, method='POST')

    def test_requires_auth(self):
        self.assertEqual(self.url_open('/api/v1/elearning/courses').status_code, 401)

    def test_classes_and_courses(self):
        headers = self._headers()
        classes = self.url_open('/api/v1/elearning/classes', headers=headers).json()['data']['classes']
        grade = next(c for c in classes if c['id'] == self.grade.id)
        self.assertEqual(grade['course_count'], 1)
        self.assertEqual(grade['sections'][0]['course_count'], 1)
        courses = self.url_open(f'/api/v1/elearning/courses?class_id={self.grade.id}', headers=headers).json()['data']
        ids = [c['id'] for c in courses['courses']]
        self.assertEqual(ids, [self.course.id])  # the draft course is hidden
        everything = self.url_open('/api/v1/elearning/courses', headers=headers).json()['data']['courses']
        self.assertNotIn(self.invite_only.id, [c['id'] for c in everything])  # members-only, not invited
        self.assertEqual(self.url_open(f'/api/v1/elearning/courses/{self.draft.id}', headers=headers).status_code, 404)

    def test_course_detail_join_and_complete(self):
        headers = self._headers()
        detail = self.url_open(f'/api/v1/elearning/courses/{self.course.id}', headers=headers).json()['data']
        self.assertFalse(detail['is_member'])
        self.assertTrue(detail['can_join'])
        self.assertEqual(detail['sections'][0]['name'], 'ElApi Basics')
        lessons = detail['sections'][0]['lessons']
        self.assertEqual([l['id'] for l in lessons], [self.article.id, self.pdf.id])
        self.assertEqual([l['locked'] for l in lessons], [True, False])
        # Members-only content: the article needs joining, the preview PDF doesn't.
        self.assertEqual(self.url_open(f'/api/v1/elearning/lessons/{self.article.id}', headers=headers)
                         .json()['error']['code'], 'join_required')
        pdf = self.url_open(f'/api/v1/elearning/lessons/{self.pdf.id}/file', headers=headers)
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.headers['Content-Type'], 'application/pdf')
        self.assertEqual(self._post(f'/api/v1/elearning/lessons/{self.pdf.id}/complete', headers)
                         .json()['error']['code'], 'join_required')

        joined = self._post(f'/api/v1/elearning/courses/{self.course.id}/join', headers)
        self.assertEqual(joined.status_code, 200, joined.text)
        self.assertTrue(joined.json()['data']['is_member'])
        self.assertEqual(joined.json()['data']['completion'], 0)
        lesson = self.url_open(f'/api/v1/elearning/lessons/{self.article.id}', headers=headers).json()['data']
        self.assertEqual(lesson['html_content'], '<p>Half</p>')
        done = self._post(f'/api/v1/elearning/lessons/{self.article.id}/complete', headers)
        self.assertEqual(done.status_code, 200, done.text)
        self.assertTrue(done.json()['data']['completed'])
        self.assertEqual(done.json()['data']['course']['completion'], 50)
        mine = self.url_open('/api/v1/elearning/courses?joined=1', headers=headers).json()['data']['courses']
        self.assertEqual([c['id'] for c in mine], [self.course.id])
        # Another user's progress is their own.
        other = self.url_open(f'/api/v1/elearning/courses/{self.course.id}', headers=self._headers(
            'elapi_other', 'OtherPass1!')).json()['data']
        self.assertFalse(other['is_member'])

    def test_invitation_only(self):
        headers = self._headers()
        self.assertEqual(self._post(f'/api/v1/elearning/courses/{self.invite_only.id}/join', headers).status_code, 404)
        self.invite_only.sudo()._action_add_members(self.student_user.partner_id, member_status='invited')
        joined = self._post(f'/api/v1/elearning/courses/{self.invite_only.id}/join', headers)
        self.assertEqual(joined.status_code, 200, joined.text)
        self.assertTrue(joined.json()['data']['is_member'])
