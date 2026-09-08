# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import HttpCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged('post_install', '-at_install')
class TestBxiLibraryBookRequest(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.teacher_user = mail_new_test_user(
            cls.env, login='book_teacher', groups='base.group_user', password='TeacherPass1!')
        cls.librarian_user = mail_new_test_user(
            cls.env, login='book_librarian',
            groups='base.group_user,bxi_library_book_request.group_book_request_librarian',
            password='LibrarianPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='book_other', groups='base.group_user', password='OtherPass1!')

        author = cls.env['op.author'].create({'name': 'Test Author'})
        publisher = cls.env['op.publisher'].create({'name': 'Test Pub'})
        genre = cls.env['op.media.genre'].create({'name': 'Fiction'})
        cls.media = cls.env['op.media'].create({
            'name': 'Sample Book', 'author_ids': [(6, 0, [author.id])],
            'publisher_ids': [(6, 0, [publisher.id])], 'genre_id': genre.id,
        })

    def _headers(self, login, password):
        resp = self.url_open('/api/v1/auth/login', json={'login': login, 'password': password})
        return {'Authorization': f'Bearer {resp.json()["data"]["token"]}'}

    def _create_request(self):
        return self.url_open('/api/v1/library/book-requests', headers=self._headers('book_teacher', 'TeacherPass1!'), json={
            'media_id': self.media.id, 'reason': 'Needed for classroom reading circle.',
        })

    def test_create_request_defaults_to_pending(self):
        resp = self._create_request()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['status'], 'pending')

    def test_create_request_missing_media_rejected(self):
        resp = self.url_open('/api/v1/library/book-requests', headers=self._headers('book_teacher', 'TeacherPass1!'), json={
            'reason': 'no media',
        })
        self.assertEqual(resp.status_code, 400)

    def test_requester_sees_only_own_requests(self):
        self._create_request()
        self.url_open('/api/v1/library/book-requests', headers=self._headers('book_other', 'OtherPass1!'), json={
            'media_id': self.media.id,
        })

        teacher_list = self.url_open('/api/v1/library/book-requests', headers=self._headers('book_teacher', 'TeacherPass1!')).json()['data']['requests']
        self.assertEqual(len(teacher_list), 1)

    def test_librarian_sees_all_requests(self):
        self._create_request()
        self.url_open('/api/v1/library/book-requests', headers=self._headers('book_other', 'OtherPass1!'), json={
            'media_id': self.media.id,
        })

        librarian_list = self.url_open('/api/v1/library/book-requests', headers=self._headers('book_librarian', 'LibrarianPass1!')).json()['data']['requests']
        self.assertEqual(len(librarian_list), 2)

    def test_non_librarian_cannot_approve(self):
        req_id = self._create_request().json()['data']['id']
        resp = self.url_open(f'/api/v1/library/book-requests/{req_id}/approve', headers=self._headers('book_teacher', 'TeacherPass1!'), method='POST')
        self.assertEqual(resp.status_code, 403)

    def test_librarian_can_approve(self):
        req_id = self._create_request().json()['data']['id']
        resp = self.url_open(f'/api/v1/library/book-requests/{req_id}/approve', headers=self._headers('book_librarian', 'LibrarianPass1!'), json={
            'notes': 'Approved for classroom use.',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['status'], 'approved')

        book_request = self.env['bxi.library.book.request'].sudo().browse(req_id)
        self.assertEqual(book_request.reviewed_by, self.librarian_user)
        self.assertTrue(book_request.reviewed_at)

    def test_librarian_can_reject(self):
        req_id = self._create_request().json()['data']['id']
        resp = self.url_open(f'/api/v1/library/book-requests/{req_id}/reject', headers=self._headers('book_librarian', 'LibrarianPass1!'), method='POST')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['status'], 'rejected')

    def test_cannot_review_already_reviewed_request(self):
        req_id = self._create_request().json()['data']['id']
        librarian_headers = self._headers('book_librarian', 'LibrarianPass1!')
        self.url_open(f'/api/v1/library/book-requests/{req_id}/approve', headers=librarian_headers, method='POST')

        second = self.url_open(f'/api/v1/library/book-requests/{req_id}/reject', headers=librarian_headers, method='POST')
        self.assertEqual(second.status_code, 400)

    def test_endpoints_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/library/book-requests').status_code, 401)

    def test_create_request_invalid_media_not_found(self):
        resp = self.url_open('/api/v1/library/book-requests', headers=self._headers('book_teacher', 'TeacherPass1!'), json={
            'media_id': self.media.id + 100000, 'reason': 'bad media id',
        })
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error']['code'], 'not_found')

    def test_create_request_links_teacher_when_requester_is_faculty(self):
        faculty = self.env['op.faculty'].create({
            'first_name': 'Book', 'last_name': 'Teacher', 'user_id': self.teacher_user.id,
            'gender': 'male',
        })
        req_id = self._create_request().json()['data']['id']
        book_request = self.env['bxi.library.book.request'].sudo().browse(req_id)
        self.assertEqual(book_request.teacher_id, faculty)

    def test_create_request_no_teacher_link_for_non_faculty_requester(self):
        req_id = self._create_request().json()['data']['id']
        book_request = self.env['bxi.library.book.request'].sudo().browse(req_id)
        self.assertFalse(book_request.teacher_id)

    def test_approve_nonexistent_request_not_found(self):
        resp = self.url_open('/api/v1/library/book-requests/999999/approve', headers=self._headers('book_librarian', 'LibrarianPass1!'), method='POST')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error']['code'], 'not_found')

    def test_reject_nonexistent_request_not_found(self):
        resp = self.url_open('/api/v1/library/book-requests/999999/reject', headers=self._headers('book_librarian', 'LibrarianPass1!'), method='POST')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error']['code'], 'not_found')

    def test_non_librarian_cannot_reject(self):
        req_id = self._create_request().json()['data']['id']
        resp = self.url_open(f'/api/v1/library/book-requests/{req_id}/reject', headers=self._headers('book_teacher', 'TeacherPass1!'), method='POST')
        self.assertEqual(resp.status_code, 403)

    def test_invalid_token_rejected(self):
        resp = self.url_open('/api/v1/library/book-requests', headers={'Authorization': 'Bearer not-a-real-token'})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()['error']['code'], 'unauthorized')

    def test_create_request_response_includes_name(self):
        resp = self._create_request()
        data = resp.json()['data']
        self.assertTrue(data.get('name'))
        self.assertNotEqual(data['name'], 'New')

    def test_cannot_approve_already_reviewed_request(self):
        req_id = self._create_request().json()['data']['id']
        librarian_headers = self._headers('book_librarian', 'LibrarianPass1!')
        self.url_open(f'/api/v1/library/book-requests/{req_id}/approve', headers=librarian_headers, method='POST')

        second = self.url_open(f'/api/v1/library/book-requests/{req_id}/approve', headers=librarian_headers, method='POST')
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()['error']['code'], 'invalid_transition')
