# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

PDF = b'%PDF-1.4\n%%EOF\n'


@tagged('post_install', '-at_install')
class TestIdDocuments(TransactionCase):
    """Uploaded ID proof (image/PDF) on students, parents and teachers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student = cls.env['op.student'].create({
            'first_name': 'Doc', 'last_name': 'Student', 'gr_no': 'IDD-001', 'gender': 'm'})
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Doc', 'last_name': 'Teacher', 'gender': 'female', 'birth_date': '1988-01-01'})

    def test_submit_replace_and_review(self):
        first = self.student._submit_id_documents([{'name': 'a.pdf', 'content': PDF, 'mimetype': 'application/pdf'}],
                                                  'aadhaar')
        self.assertEqual(self.student.id_document_status, 'pending')
        self.assertEqual(self.student.id_document_type, 'aadhaar')
        self.assertEqual(self.student.id_document_ids, first)
        self.assertEqual(first.res_model, 'op.student')
        self.student.action_reject_id_document()
        self.assertEqual(self.student.id_document_status, 'rejected')

        second = self.student._submit_id_documents([{'name': 'b.pdf', 'content': PDF}])
        self.assertEqual(self.student.id_document_ids, second)
        self.assertFalse(first.exists(), 'The replaced document is deleted.')
        self.assertEqual(self.student.id_document_type, 'aadhaar', 'The type is kept when not given.')
        self.student.action_verify_id_document()
        self.assertEqual(self.student.id_document_status, 'verified')
        self.assertTrue(self.student.id_document_verified_at)

    def test_teachers_have_identity_verification(self):
        self.assertEqual(self.faculty.id_document_status, 'unverified')
        self.faculty._submit_id_documents([{'name': 'id.pdf', 'content': PDF}], 'pan')
        self.assertEqual(self.faculty.id_document_status, 'pending')
        self.assertEqual(self.faculty.face_verification_status, 'unverified')

    def test_document_required(self):
        with self.assertRaises(UserError):
            self.student._submit_id_documents([])
