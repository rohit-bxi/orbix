# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged('post_install', '-at_install')
class TestBxiLibraryBookRequestModel(TransactionCase):
    """Model-level unit tests for bxi.library.book.request, one-to-one per
    model method. These call the model methods directly, unlike
    tests/test_book_request.py which exercises the HTTP controller layer.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.teacher_user = mail_new_test_user(
            cls.env, login='model_book_teacher', groups='base.group_user', password='TeacherPass1!')
        cls.librarian_user = mail_new_test_user(
            cls.env, login='model_book_librarian',
            groups='base.group_user,bxi_library_book_request.group_book_request_librarian',
            password='LibrarianPass1!')

        author = cls.env['op.author'].create({'name': 'Model Test Author'})
        publisher = cls.env['op.publisher'].create({'name': 'Model Test Pub'})
        genre = cls.env['op.media.genre'].create({'name': 'Model Fiction'})
        cls.media = cls.env['op.media'].create({
            'name': 'Model Sample Book', 'author_ids': [(6, 0, [author.id])],
            'publisher_ids': [(6, 0, [publisher.id])], 'genre_id': genre.id,
        })

    def _create_pending(self):
        return self.env['bxi.library.book.request'].create({
            'requester_user_id': self.teacher_user.id,
            'media_id': self.media.id,
            'reason': 'Model-level test request.',
        })

    # -- create() -----------------------------------------------------

    def test_create_assigns_sequence_name(self):
        """create() should populate name from ir.sequence when not given."""
        request = self._create_pending()
        self.assertTrue(request.name)
        self.assertNotEqual(request.name, 'New')

    def test_create_preserves_explicit_name(self):
        """create() should not overwrite a name explicitly provided."""
        request = self.env['bxi.library.book.request'].create({
            'requester_user_id': self.teacher_user.id,
            'media_id': self.media.id,
            'name': 'CUSTOM-001',
        })
        self.assertEqual(request.name, 'CUSTOM-001')

    # -- action_approve() ----------------------------------------------

    def test_action_approve_success(self):
        """action_approve() on a pending request sets status/reviewer/notes."""
        request = self._create_pending()
        request.with_user(self.librarian_user).action_approve(notes='Looks good.')
        self.assertEqual(request.status, 'approved')
        self.assertEqual(request.reviewed_by, self.librarian_user)
        self.assertTrue(request.reviewed_at)
        self.assertEqual(request.review_notes, 'Looks good.')

    def test_action_approve_invalid_transition_raises(self):
        """action_approve() on a non-pending request raises UserError."""
        request = self._create_pending()
        request.with_user(self.librarian_user).action_approve()
        with self.assertRaises(UserError):
            request.with_user(self.librarian_user).action_approve()

    # -- action_reject() ------------------------------------------------

    def test_action_reject_success(self):
        """action_reject() on a pending request sets status/reviewer/notes."""
        request = self._create_pending()
        request.with_user(self.librarian_user).action_reject(notes='Not needed.')
        self.assertEqual(request.status, 'rejected')
        self.assertEqual(request.reviewed_by, self.librarian_user)
        self.assertTrue(request.reviewed_at)
        self.assertEqual(request.review_notes, 'Not needed.')

    def test_action_reject_invalid_transition_raises(self):
        """action_reject() on a non-pending request raises UserError."""
        request = self._create_pending()
        request.with_user(self.librarian_user).action_reject()
        with self.assertRaises(UserError):
            request.with_user(self.librarian_user).action_reject()
