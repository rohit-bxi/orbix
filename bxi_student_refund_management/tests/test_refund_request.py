# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStudentRefundRequest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_accounting()

        cls.student = cls.env['op.student'].create({
            'first_name': 'Refund', 'last_name': 'Student', 'gr_no': 'REF-001', 'gender': 'm',
        })
        cls.student.partner_id.property_account_receivable_id = cls.receivable_account
        # Fee total 1000, paid 1200 => the student overpaid by 200.
        cls._create_posted_invoice(cls.student, 1000.0, 1200.0)

        cls.other_student = cls.env['op.student'].create({
            'first_name': 'NoExcess', 'last_name': 'Student', 'gr_no': 'REF-002', 'gender': 'f',
        })
        cls.other_student.partner_id.property_account_receivable_id = cls.receivable_account
        # Fee total 1000, paid 400 => no excess, still pending.
        cls._create_posted_invoice(cls.other_student, 1000.0, 400.0)

    @classmethod
    def _setup_accounting(cls):
        company = cls.env.company
        cls.income_account = cls.env['account.account'].search(
            [('account_type', '=', 'income'), ('company_ids', 'in', company.id)], limit=1)
        if not cls.income_account:
            cls.income_account = cls.env['account.account'].create({
                'name': 'Test Income', 'code': 'TINC03', 'account_type': 'income',
                'company_ids': [(6, 0, [company.id])],
            })
        cls.receivable_account = cls.env['account.account'].search(
            [('account_type', '=', 'asset_receivable'), ('company_ids', 'in', company.id)], limit=1)
        if not cls.receivable_account:
            cls.receivable_account = cls.env['account.account'].create({
                'name': 'Test Receivable', 'code': 'TREC03', 'account_type': 'asset_receivable',
                'reconcile': True, 'company_ids': [(6, 0, [company.id])],
            })
        cls.sale_journal = cls.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', company.id)], limit=1)
        if not cls.sale_journal:
            cls.sale_journal = cls.env['account.journal'].create({
                'name': 'Test Sales Journal', 'type': 'sale', 'code': 'TSJ03',
            })
        cls.cash_journal = cls.env['account.journal'].search(
            [('type', '=', 'cash'), ('company_id', '=', company.id)], limit=1)
        if not cls.cash_journal:
            cls.cash_journal = cls.env['account.journal'].create({
                'name': 'Test Cash Journal', 'type': 'cash', 'code': 'TCJ03',
            })

    @classmethod
    def _create_posted_invoice(cls, student, total, paid):
        invoice = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': student.partner_id.id,
            'journal_id': cls.sale_journal.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Test Fee',
                'account_id': cls.income_account.id,
                'price_unit': total,
                'quantity': 1.0,
                'tax_ids': [(5, 0, 0)],
            })],
        })
        invoice.action_post()
        if paid:
            register = cls.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=invoice.ids,
            ).create({'amount': paid, 'journal_id': cls.cash_journal.id})
            register.action_create_payments()
        return invoice

    def _make_refund(self, student=None, **kwargs):
        vals = {
            'student_id': (student or self.student).id,
            'refund_type': 'fee_overpayment',
            'refund_amount': 150.0,
            'reason': 'Overpaid tuition fee',
        }
        vals.update(kwargs)
        return self.env['bxi.student.refund.request'].create(vals)

    # -- Payment summary / money math --------------------------------------------

    def test_payment_summary_matches_invoice(self):
        refund = self._make_refund()
        self.assertAlmostEqual(refund.total_fee_amount, 1000.0)
        self.assertAlmostEqual(refund.total_paid_amount, 1200.0)
        self.assertAlmostEqual(refund.excess_amount, 200.0)
        self.assertAlmostEqual(refund.pending_amount, 0.0)

    def test_refund_amount_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self._make_refund(refund_amount=0.0)

    def test_refund_cannot_exceed_total_paid(self):
        # Student paid 1200 total; requesting more than that must be blocked
        # even though it's nominally a "fee_overpayment" refund.
        with self.assertRaises(ValidationError):
            self._make_refund(refund_amount=1500.0)

    def test_refund_up_to_total_paid_allowed(self):
        refund = self._make_refund(refund_amount=1200.0)
        self.assertEqual(refund.refund_amount, 1200.0)

    def test_refund_blocked_when_no_excess_exists(self):
        # other_student paid only 400 of 1000, so any refund_amount > total_paid_amount
        # (400) must be rejected, even though it's a small amount.
        with self.assertRaises(ValidationError):
            self._make_refund(student=self.other_student, refund_amount=500.0)
        # But a refund within what was actually paid is allowed (e.g. a mistaken payment).
        refund = self._make_refund(student=self.other_student, refund_amount=300.0)
        self.assertEqual(refund.refund_amount, 300.0)

    # -- Status workflow ------------------------------------------------------------

    def test_status_guard_blocks_approve_before_submit(self):
        refund = self._make_refund()
        with self.assertRaises(UserError):
            refund.action_approve()

    def test_full_approval_and_processing_lifecycle(self):
        refund = self._make_refund()
        refund.action_submit()
        self.assertEqual(refund.status, 'pending_review')
        refund.action_start_review()
        self.assertEqual(refund.status, 'under_review')
        refund.action_approve()
        self.assertEqual(refund.status, 'approved')
        self.assertEqual(refund.approved_by, self.env.user)
        refund.action_start_processing()
        self.assertEqual(refund.status, 'processing')
        with self.assertRaises(ValidationError):
            refund.action_complete()  # UTR/reference not entered yet
        refund.refund_utr = 'UTR123456'
        refund.action_complete()
        self.assertEqual(refund.status, 'completed')
        self.assertTrue(refund.refund_completion_date)

    def test_approve_and_process_shortcut(self):
        refund = self._make_refund()
        refund.action_submit()
        refund.action_approve_and_process()
        self.assertEqual(refund.status, 'processing')

    def test_reject_allowed_after_approval(self):
        refund = self._make_refund()
        refund.action_submit()
        refund.action_approve()
        refund.action_reject()
        self.assertEqual(refund.status, 'rejected')

    def test_reset_to_draft_clears_processing_fields(self):
        refund = self._make_refund()
        refund.action_submit()
        refund.action_approve()
        refund.action_reset_to_draft()
        self.assertEqual(refund.status, 'draft')
        self.assertFalse(refund.approved_by)
        self.assertFalse(refund.approval_date)

    def test_days_pending_zero_when_draft(self):
        refund = self._make_refund()
        self.assertEqual(refund.days_pending, 0)

    # -- Bulk refund wizard -----------------------------------------------------------

    def test_bulk_wizard_full_excess_amount(self):
        wizard = self.env['bxi.refund.bulk.wizard'].create({
            'student_ids': [(6, 0, [self.student.id])],
            'refund_type': 'fee_overpayment',
            'refund_amount_calculation': 'full_excess_amount',
            'reason': 'Bulk refund of overpayments',
        })
        self.assertAlmostEqual(wizard.total_refund_amount, 200.0)
        action = wizard.action_process_refunds()
        created = self.env['bxi.student.refund.request'].search(action['domain'])
        self.assertEqual(len(created), 1)
        self.assertAlmostEqual(created.refund_amount, 200.0)

    def test_bulk_wizard_percentage_of_excess(self):
        wizard = self.env['bxi.refund.bulk.wizard'].create({
            'student_ids': [(6, 0, [self.student.id])],
            'refund_type': 'fee_overpayment',
            'refund_amount_calculation': 'percentage_of_excess',
            'refund_percentage': 50.0,
            'reason': 'Half refund',
        })
        self.assertAlmostEqual(wizard.total_refund_amount, 100.0)

    def test_bulk_wizard_blocks_student_without_excess(self):
        wizard = self.env['bxi.refund.bulk.wizard'].create({
            'student_ids': [(6, 0, [self.other_student.id])],
            'refund_type': 'fee_overpayment',
            'refund_amount_calculation': 'full_excess_amount',
            'reason': 'Should fail, no excess',
        })
        with self.assertRaises(ValidationError):
            wizard.action_process_refunds()

    def test_bulk_wizard_requires_at_least_one_student(self):
        wizard = self.env['bxi.refund.bulk.wizard'].create({
            'refund_type': 'fee_overpayment',
            'reason': 'No students selected',
        })
        with self.assertRaises(ValidationError):
            wizard.action_process_refunds()

    # -- Delete wizard --------------------------------------------------------------

    def test_delete_wizard_requires_all_confirmations(self):
        refund = self._make_refund()
        wizard = self.env['bxi.refund.delete.wizard'].create({
            'refund_request_id': refund.id,
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm_delete()
        wizard.write({
            'confirmation_text': 'delete',  # case-insensitive
            'understand_permanent': True,
            'notify_parent_of_deletion': True,
        })
        wizard.action_confirm_delete()
        self.assertFalse(refund.exists())
