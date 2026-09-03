# -*- coding: utf-8 -*-

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import TestRteAdmissionCommon


@tagged('post_install', '-at_install')
class TestOpAdmission(TestRteAdmissionCommon):

    def test_defaults_for_rte_applicant(self):
        admission = self._make_admission()
        self.assertTrue(admission.is_rte_applicant)
        self.assertEqual(admission.rte_state, 'draft')

    def test_verify_documents_from_draft(self):
        admission = self._make_admission()
        doc = self.env['rte.document'].create({
            'admission_id': admission.id,
            'doc_type': 'income_cert',
        })
        self.assertEqual(doc.verification_status, 'pending')

        message_count_before = len(admission.message_ids)
        admission.action_verify_documents()

        self.assertEqual(admission.rte_state, 'doc_verified')
        self.assertEqual(doc.verification_status, 'verified')
        self.assertEqual(admission.verified_by, self.env.user)
        self.assertTrue(admission.verification_date)
        self.assertGreater(len(admission.message_ids), message_count_before)

    def test_verify_documents_invalid_state_raises(self):
        admission = self._make_admission()
        admission.action_verify_documents()  # draft -> doc_verified
        admission.rte_state = 'lottery_pending'
        with self.assertRaises(UserError):
            admission.action_verify_documents()

    def test_reject_documents_from_draft(self):
        admission = self._make_admission()
        doc = self.env['rte.document'].create({
            'admission_id': admission.id,
            'doc_type': 'address_proof',
        })
        admission.rejection_reason = 'Missing address proof.'
        message_count_before = len(admission.message_ids)
        admission.action_reject_documents()

        self.assertEqual(admission.rte_state, 'doc_rejected')
        self.assertEqual(doc.verification_status, 'rejected')
        self.assertGreater(len(admission.message_ids), message_count_before)

    def test_reject_documents_invalid_state_raises(self):
        admission = self._make_admission()
        admission.rte_state = 'confirmed'
        with self.assertRaises(UserError):
            admission.action_reject_documents()

    def test_verify_after_reject_is_allowed(self):
        # action_verify_documents allows draft or doc_rejected.
        admission = self._make_admission()
        admission.action_reject_documents()
        self.assertEqual(admission.rte_state, 'doc_rejected')
        admission.action_verify_documents()
        self.assertEqual(admission.rte_state, 'doc_verified')
        # rejection_reason is cleared on (re-)verification.
        self.assertFalse(admission.rejection_reason)

    def test_confirm_admission_from_allotted(self):
        admission = self._make_admission()
        admission.rte_state = 'allotted'
        admission.action_confirm_admission()
        self.assertEqual(admission.rte_state, 'confirmed')

    def test_confirm_admission_from_waitlisted(self):
        admission = self._make_admission()
        admission.rte_state = 'waitlisted'
        admission.action_confirm_admission()
        self.assertEqual(admission.rte_state, 'confirmed')

    def test_confirm_admission_invalid_state_raises(self):
        admission = self._make_admission()
        with self.assertRaises(UserError):
            admission.action_confirm_admission()  # still draft

    def test_mark_admitted_from_confirmed(self):
        admission = self._make_admission()
        admission.rte_state = 'confirmed'
        admission.action_mark_admitted()
        self.assertEqual(admission.rte_state, 'admitted')

    def test_mark_admitted_invalid_state_raises(self):
        admission = self._make_admission()
        with self.assertRaises(UserError):
            admission.action_mark_admitted()  # still draft

    def test_mark_lapsed_from_allotted(self):
        admission = self._make_admission()
        admission.rte_state = 'allotted'
        admission.action_mark_lapsed()
        self.assertEqual(admission.rte_state, 'lapsed')

    def test_mark_lapsed_blocked_when_admitted(self):
        admission = self._make_admission()
        admission.rte_state = 'admitted'
        with self.assertRaises(UserError):
            admission.action_mark_lapsed()

    def test_mark_lapsed_blocked_when_already_lapsed(self):
        admission = self._make_admission()
        admission.rte_state = 'lapsed'
        with self.assertRaises(UserError):
            admission.action_mark_lapsed()

    def test_mark_lapsed_blocked_from_draft(self):
        # A brand-new application must go through verification/lottery
        # before it can be lapsed.
        admission = self._make_admission()
        with self.assertRaises(UserError):
            admission.action_mark_lapsed()

    def test_mark_lapsed_from_confirmed(self):
        admission = self._make_admission()
        admission.rte_state = 'confirmed'
        admission.action_mark_lapsed()
        self.assertEqual(admission.rte_state, 'lapsed')
