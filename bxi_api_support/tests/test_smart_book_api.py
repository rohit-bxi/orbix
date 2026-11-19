# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The Smart Books Management, Add Smart Book and Edit Smart Book screens
on /api/v1/academic/smart-books, plus the curriculum dropdown."""
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase

URL = '/api/v1/academic/smart-books'


@tagged('post_install', '-at_install')
class TestSmartBookApi(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mail_new_test_user(cls.env, login='sb_coordinator', password='CoordPass1!',
                           groups='base.group_user,bxi_academic_management.group_academic_coordinator')
        mail_new_test_user(cls.env, login='sb_staff', password='StaffPass1!', groups='base.group_user')
        mail_new_test_user(cls.env, login='sb_portal', password='PortalPass1!', groups='base.group_portal')
        Course = cls.env['op.course']
        cls.class9 = Course.create({'name': 'SB Class 9', 'code': 'SB-9'})
        cls.class10 = Course.create({'name': 'SB Class 10', 'code': 'SB-10'})
        cls.class11 = Course.create({'name': 'SB Class 11', 'code': 'SB-11'})
        Subject = cls.env['op.subject']
        cls.maths = Subject.create({'name': 'SB Mathematics', 'code': 'SB-MATH'})
        cls.science = Subject.create({'name': 'SB Science', 'code': 'SB-SCI'})
        board = cls.env['bxi.board'].create({'name': 'SB CBSE'})
        Curriculum = cls.env['bxi.curriculum']
        cls.cbse26 = Curriculum.create({
            'name': 'SB CBSE 2026', 'board_id': board.id, 'description': 'x', 'approval_status': 'approved',
            'class_ids': [(6, 0, (cls.class9 | cls.class10).ids)]})
        cls.cbse24 = Curriculum.create({'name': 'SB CBSE 2024', 'board_id': board.id, 'description': 'x'})
        cls.rejected = Curriculum.create({'name': 'SB Old', 'board_id': board.id, 'description': 'x',
                                          'approval_status': 'rejected'})

    def _post(self, url, body, login='sb_coordinator', password='CoordPass1!'):
        return self.url_open(url, headers=self._headers(login, password), json=body, method='POST')

    def _get(self, url, login='sb_staff', password='StaffPass1!'):
        return self.url_open(url, headers=self._headers(login, password))

    def _error(self, resp, status, code):
        self.assertEqual(resp.status_code, status, resp.text)
        self.assertEqual(resp.json()['error']['code'], code)

    def _create(self, **overrides):
        body = {'title': 'Mathematics Grade 9', 'subject_ids': [self.maths.id], 'class_ids': [self.class9.id],
                'curriculum_id': self.cbse26.id}
        # Names as typed replace the ids (the ids key wins when both are sent).
        for names, ids in (('subjects', 'subject_ids'), ('classes', 'class_ids')):
            if names in overrides:
                body.pop(ids)
        body.update(overrides)
        return self._post(URL, body)

    def test_add_smart_book(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertEqual(data['title'], 'Mathematics Grade 9')
        self.assertEqual(data['subjects'], [{'id': self.maths.id, 'name': self.maths.display_name}])
        self.assertEqual(data['classes'], [{'id': self.class9.id, 'name': self.class9.display_name}])
        self.assertEqual(data['curriculum'], {'id': self.cbse26.id, 'name': 'SB CBSE 2026',
                                              'approval_status': 'approved'})
        self.assertEqual((data['locked'], data['active']), (False, True))
        book = self.env['op.media'].browse(data['id'])
        self.assertFalse(book.author_ids or book.publisher_ids or book.genre_id,
                         'The screen sends no library details and needs none.')

        # Names as typed on the screen: a comma-separated string or a list.
        typed = self._create(title='Science Grade 9 & 10', subjects='sb science', classes='SB Class 9, sb-10')
        self.assertEqual(typed.status_code, 201, typed.text)
        self.assertEqual(typed.json()['data']['class_ids'], [self.class9.id, self.class10.id])
        self.assertEqual(typed.json()['data']['subject_ids'], [self.science.id])

        listed = self._get(URL + '?curriculum_id=%s' % self.cbse26.id).json()
        self.assertEqual(listed['meta']['total'], 2)
        self.assertEqual(self._get(URL + '?q=science').json()['meta']['total'], 1)
        self.assertEqual(self._get(URL + '?subject_id=%s' % self.maths.id).json()['meta']['total'], 1)
        self.assertEqual(self._get(URL + '?class_id=%s' % self.class10.id).json()['meta']['total'], 1)
        self.assertEqual(self._get(URL + '/%s' % data['id']).json()['data']['title'], 'Mathematics Grade 9')

    def test_required_fields_and_checks(self):
        for key in ('title', 'subject_ids', 'class_ids', 'curriculum_id'):
            self._error(self._create(**{key: '' if key == 'title' else ([] if key.endswith('_ids') else None)}),
                        400, 'missing_%s' % key)
        self._error(self._create(subjects=['Astrology']), 400, 'unknown_subject')
        self._error(self._create(curriculum_id=self.rejected.id), 400, 'curriculum_rejected')
        self._error(self._create(class_ids=[self.class11.id]), 400, 'class_not_in_curriculum')
        # A curriculum with no classes assigned yet takes any class.
        self.assertEqual(self._create(curriculum_id=self.cbse24.id, class_ids=[self.class11.id]).status_code, 201)
        self.assertEqual(self._create().status_code, 201)
        self._error(self._create(title='mathematics grade 9'), 409, 'smart_book_exists')

        self._error(self._post(URL, {'title': 'X'}, 'sb_staff', 'StaffPass1!'), 403, 'forbidden')
        self._error(self._get(URL, 'sb_portal', 'PortalPass1!'), 403, 'forbidden')

    def test_edit_smart_book(self):
        data = self._create().json()['data']
        url = URL + '/%s/update' % data['id']
        resp = self._post(url, {'title': 'Mathematics Grade 10', 'class_ids': [self.class10.id],
                                'subjects': ['SB Mathematics', 'SB Science']})
        self.assertEqual(resp.status_code, 200, resp.text)
        result = resp.json()['data']
        self.assertEqual((result['title'], result['class_ids']), ('Mathematics Grade 10', [self.class10.id]))
        self.assertEqual(len(result['subject_ids']), 2)
        self.assertEqual(result['curriculum_id'], self.cbse26.id, 'Keys not sent are kept.')

        moved = self._post(url, {'curriculum_id': self.cbse24.id})
        self.assertEqual(moved.json()['data']['curriculum']['name'], 'SB CBSE 2024')
        self._error(self._post(url, {'class_ids': []}), 400, 'missing_class_ids')
        self._error(self._post(url, {'curriculum_id': None}), 400, 'missing_curriculum_id')

        library_book = self.env['op.media'].search([('curriculum_id', '=', False)], limit=1)
        if library_book:
            self._error(self._post(URL + '/%s/update' % library_book.id, {'title': 'X'}), 404, 'not_found')

    def test_lock_and_delete(self):
        data = self._create().json()['data']
        lock_url = URL + '/%s/toggle-lock' % data['id']
        self.assertTrue(self._post(lock_url, {}).json()['data']['locked'])
        self._error(self._post(URL + '/%s/update' % data['id'], {'title': 'Y'}), 409, 'smart_book_locked')
        self._error(self._post(URL + '/%s/delete' % data['id'], {}), 409, 'smart_book_locked')
        self.assertFalse(self._post(lock_url, {}).json()['data']['locked'])

        resp = self._post(URL + '/%s/delete' % data['id'], {})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data'], {'id': data['id'], 'deleted': True, 'archived': False})
        self.assertFalse(self.env['op.media'].browse(data['id']).exists())
        self._error(self._post(URL + '/%s/delete' % data['id'], {}), 404, 'not_found')

        # A book that has been reserved keeps its history: archived instead.
        kept = self._create(title='Reserved Book').json()['data']
        self.env['op.media.queue'].create({'media_id': kept['id'], 'date_to': fields.Date.today()})
        resp = self._post(URL + '/%s/delete' % kept['id'], {})
        self.assertEqual(resp.json()['data'], {'id': kept['id'], 'deleted': False, 'archived': True})
        self.assertFalse(self.env['op.media'].with_context(active_test=False).browse(kept['id']).active)

    def test_curriculum_dropdown(self):
        resp = self._get('/api/v1/academic/curricula?status=approved&limit=100')
        names = [c['name'] for c in resp.json()['data']['curricula']]
        self.assertIn('SB CBSE 2026', names)
        self.assertNotIn('SB CBSE 2024', names)
        self._error(self._get('/api/v1/academic/curricula?status=open'), 400, 'invalid_status')

    def test_library_books_still_need_library_details(self):
        with self.assertRaises(ValidationError):
            self.env['op.media'].create({'name': 'Plain Library Book'})
