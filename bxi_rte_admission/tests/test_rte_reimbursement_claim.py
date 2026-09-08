# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import TestRteAdmissionCommon


@tagged('post_install', '-at_install')
class TestRteReimbursementClaim(TestRteAdmissionCommon):

    def _make_claim(self, **kwargs):
        vals = {
            'course_id': self.course.id,
            'academic_year_id': self.academic_year.id,
            'amount': 5000.0,
        }
        vals.update(kwargs)
        return self.env['rte.reimbursement.claim'].create(vals)

    def test_claim_gets_sequence_name_on_create(self):
        claim = self._make_claim()
        self.assertTrue(claim.name)
        self.assertNotEqual(claim.name, 'New')

    def test_default_state_is_draft(self):
        claim = self._make_claim()
        self.assertEqual(claim.state, 'draft')

    def test_full_lifecycle_submit_approve_paid(self):
        claim = self._make_claim()
        claim.action_submit()
        self.assertEqual(claim.state, 'submitted')
        claim.action_approve()
        self.assertEqual(claim.state, 'approved')
        claim.action_mark_paid()
        self.assertEqual(claim.state, 'paid')

    def test_submit_guarded_against_non_draft(self):
        claim = self._make_claim()
        claim.action_submit()
        with self.assertRaises(UserError):
            claim.action_submit()  # already submitted

    def test_approve_guarded_against_non_submitted(self):
        claim = self._make_claim()
        with self.assertRaises(UserError):
            claim.action_approve()  # still draft

    def test_reject_allowed_from_submitted(self):
        claim = self._make_claim()
        claim.action_submit()
        claim.action_reject()
        self.assertEqual(claim.state, 'rejected')

    def test_reject_allowed_from_approved(self):
        claim = self._make_claim()
        claim.action_submit()
        claim.action_approve()
        claim.action_reject()
        self.assertEqual(claim.state, 'rejected')

    def test_reject_guarded_against_draft(self):
        claim = self._make_claim()
        with self.assertRaises(UserError):
            claim.action_reject()  # still draft

    def test_mark_paid_guarded_against_non_approved(self):
        claim = self._make_claim()
        claim.action_submit()
        with self.assertRaises(UserError):
            claim.action_mark_paid()  # only submitted, not approved

    def test_mark_paid_guarded_against_rejected(self):
        claim = self._make_claim()
        claim.action_submit()
        claim.action_reject()
        with self.assertRaises(UserError):
            claim.action_mark_paid()
