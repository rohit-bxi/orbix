# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo.tests.common import tagged

from .common import TestRteAdmissionCommon


@tagged('post_install', '-at_install')
class TestRteDocument(TestRteAdmissionCommon):

    def test_default_verification_status_is_pending(self):
        admission = self._make_admission()
        doc = self.env['rte.document'].create({
            'admission_id': admission.id,
            'doc_type': 'birth_cert',
        })
        self.assertEqual(doc.verification_status, 'pending')

    def test_change_verification_status_to_verified(self):
        admission = self._make_admission()
        doc = self.env['rte.document'].create({
            'admission_id': admission.id,
            'doc_type': 'category_cert',
        })
        doc.verification_status = 'verified'
        self.assertEqual(doc.verification_status, 'verified')

    def test_change_verification_status_to_rejected(self):
        admission = self._make_admission()
        doc = self.env['rte.document'].create({
            'admission_id': admission.id,
            'doc_type': 'disability_cert',
            'remarks': 'Illegible copy',
        })
        doc.verification_status = 'rejected'
        self.assertEqual(doc.verification_status, 'rejected')
        self.assertEqual(doc.remarks, 'Illegible copy')

    def test_document_deleted_when_admission_deleted(self):
        admission = self._make_admission()
        doc = self.env['rte.document'].create({
            'admission_id': admission.id,
            'doc_type': 'income_cert',
        })
        doc_id = doc.id
        admission.unlink()
        self.assertFalse(self.env['rte.document'].search([('id', '=', doc_id)]))
