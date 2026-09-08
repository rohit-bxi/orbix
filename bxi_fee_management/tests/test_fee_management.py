# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFeeManagement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_accounting()

        cls.student = cls.env['op.student'].create({
            'first_name': 'Fee', 'last_name': 'Payer', 'gr_no': 'FEE-001', 'gender': 'm',
        })
        cls.student.partner_id.property_account_receivable_id = cls.receivable_account

        cls.product = cls.env['product.product'].create({
            'name': 'Tuition Fee',
            'lst_price': 1000.0,
            'property_account_income_id': cls.income_account.id,
            'taxes_id': [(5, 0, 0)],
        })
        cls.fee_category = cls.env['bxi.fee.category'].create({
            'name': 'Tuition',
            'code': 'TUI',
            'product_id': cls.product.id,
            'default_frequency': 'annual',
        })
        cls.structure = cls.env['op.fees.terms'].create({
            'name': 'Standard Fee Structure',
            'code': 'SFS001',
            'fees_terms': 'fixed_date',
            'line_ids': [(0, 0, {'due_date': fields.Date.today(), 'value': 100.0})],
            'category_line_ids': [(0, 0, {
                'category_id': cls.fee_category.id, 'amount': 1000.0, 'frequency': 'annual',
            })],
            'installment_type': 'one_time',
            'first_due_date': fields.Date.today(),
            'allow_partial_payment': True,
        })
        cls.structure._sync_category_lines_to_elements()

    @classmethod
    def _setup_accounting(cls):
        company = cls.env.company
        cls.income_account = cls.env['account.account'].search(
            [('account_type', '=', 'income'), ('company_ids', 'in', company.id)], limit=1)
        if not cls.income_account:
            cls.income_account = cls.env['account.account'].create({
                'name': 'Test Income', 'code': 'TINC01', 'account_type': 'income',
                'company_ids': [(6, 0, [company.id])],
            })
        cls.receivable_account = cls.env['account.account'].search(
            [('account_type', '=', 'asset_receivable'), ('company_ids', 'in', company.id)], limit=1)
        if not cls.receivable_account:
            cls.receivable_account = cls.env['account.account'].create({
                'name': 'Test Receivable', 'code': 'TREC01', 'account_type': 'asset_receivable',
                'reconcile': True, 'company_ids': [(6, 0, [company.id])],
            })
        cls.sale_journal = cls.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', company.id)], limit=1)
        if not cls.sale_journal:
            cls.sale_journal = cls.env['account.journal'].create({
                'name': 'Test Sales Journal', 'type': 'sale', 'code': 'TSJ01',
            })
        cls.cash_journal = cls.env['account.journal'].search(
            [('type', '=', 'cash'), ('company_id', '=', company.id)], limit=1)
        if not cls.cash_journal:
            cls.cash_journal = cls.env['account.journal'].create({
                'name': 'Test Cash Journal', 'type': 'cash', 'code': 'TCJ01',
            })

    def _make_detail(self, amount=1000.0, date=None, discount=0.0):
        return self.env['op.student.fees.details'].create({
            'student_id': self.student.id,
            'fees_line_id': self.structure.line_ids[0].id,
            'product_id': self.product.id,
            'amount': amount,
            'discount': discount,
            'date': date or fields.Date.today(),
            'state': 'draft',
        })

    # -- Fee Category / Structure -------------------------------------------------

    def test_structure_total_amount_compute(self):
        self.assertEqual(self.structure.total_amount, 1000.0)

    def test_category_line_amount_must_be_positive(self):
        with self.assertRaises(UserError):
            self.env['bxi.fee.structure.category.line'].create({
                'structure_id': self.structure.id,
                'category_id': self.fee_category.id,
                'amount': 0.0,
            })

    def test_generate_installments_multiple_sums_to_100(self):
        self.structure.write({'installment_type': 'n_installments', 'installment_count': 3})
        self.structure.action_generate_installments()
        self.assertEqual(len(self.structure.line_ids), 3)
        self.assertAlmostEqual(sum(self.structure.line_ids.mapped('value')), 100.0)

    def test_activate_requires_category_lines(self):
        empty_structure = self.env['op.fees.terms'].create({
            'name': 'Empty Structure',
            'code': 'EMP001',
            'line_ids': [(0, 0, {'due_date': fields.Date.today(), 'value': 100.0})],
        })
        with self.assertRaises(UserError):
            empty_structure.action_activate()

    def test_activate_success_then_deactivate_wizard(self):
        self.structure.action_activate()
        self.assertEqual(self.structure.state, 'active')
        wizard = self.env['bxi.fee.structure.deactivate.wizard'].create({
            'structure_id': self.structure.id,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()
        wizard.write({'ack_impact': True, 'ack_reviewed': True})
        wizard.action_confirm()
        self.assertEqual(self.structure.state, 'inactive')

    # -- Late fee / collection status ---------------------------------------------

    def test_late_fee_fixed_type_marks_overdue(self):
        self.structure.write({
            'late_fee_enabled': True, 'late_fee_type': 'fixed',
            'late_fee_amount': 50.0, 'late_fee_apply_after_days': 0, 'grace_period_days': 0,
        })
        detail = self._make_detail(date=fields.Date.today() - timedelta(days=5))
        self.assertEqual(detail.collection_status, 'overdue')
        self.assertEqual(detail.late_fee_amount, 50.0)
        self.assertEqual(detail.total_payable, 1050.0)
        self.assertEqual(detail.amount_pending, 1050.0)

    def test_late_fee_percentage_type(self):
        self.structure.write({
            'late_fee_enabled': True, 'late_fee_type': 'percentage',
            'late_fee_amount': 10.0, 'late_fee_apply_after_days': 0, 'grace_period_days': 0,
        })
        detail = self._make_detail(
            amount=1000.0, discount=0.0,
            date=fields.Date.today() - timedelta(days=3))
        # 10% of after_discount_amount (1000.0)
        self.assertEqual(detail.late_fee_amount, 100.0)
        self.assertEqual(detail.total_payable, 1100.0)

    def test_late_fee_per_day_type_capped(self):
        self.structure.write({
            'late_fee_enabled': True, 'late_fee_type': 'per_day',
            'late_fee_amount': 20.0, 'late_fee_max_cap': 60.0,
            'late_fee_apply_after_days': 0, 'grace_period_days': 0,
        })
        detail = self._make_detail(
            date=fields.Date.today() - timedelta(days=10))
        # 20 * 10 days = 200, capped at 60
        self.assertEqual(detail.late_fee_amount, 60.0)

    def test_no_late_fee_before_apply_after_days(self):
        self.structure.write({
            'late_fee_enabled': True, 'late_fee_type': 'fixed',
            'late_fee_amount': 50.0, 'late_fee_apply_after_days': 10, 'grace_period_days': 0,
        })
        detail = self._make_detail(
            date=fields.Date.today() - timedelta(days=3))
        self.assertEqual(detail.late_fee_amount, 0.0)
        self.assertEqual(detail.collection_status, 'pending')

    def test_collection_status_cancel_overrides_overdue(self):
        detail = self._make_detail(date=fields.Date.today() - timedelta(days=30))
        detail.state = 'cancel'
        self.assertEqual(detail.collection_status, 'pending')

    # -- Payment wizard guards ------------------------------------------------------

    def test_payment_wizard_zero_amount_blocked(self):
        detail = self._make_detail()
        wizard = self.env['bxi.fee.payment.wizard'].create({
            'fees_detail_id': detail.id, 'amount': 0.0,
            'payment_mode': 'cash', 'journal_id': self.cash_journal.id,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()

    def test_payment_wizard_amount_exceeds_pending_blocked(self):
        detail = self._make_detail(amount=500.0)
        wizard = self.env['bxi.fee.payment.wizard'].create({
            'fees_detail_id': detail.id, 'amount': 1000.0,
            'payment_mode': 'cash', 'journal_id': self.cash_journal.id,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()

    def test_payment_wizard_partial_not_allowed(self):
        self.structure.write({'allow_partial_payment': False})
        detail = self._make_detail(amount=1000.0)
        wizard = self.env['bxi.fee.payment.wizard'].create({
            'fees_detail_id': detail.id, 'amount': 400.0,
            'payment_mode': 'cash', 'journal_id': self.cash_journal.id,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()

    def test_payment_wizard_full_payment_flow(self):
        detail = self._make_detail(amount=1000.0)
        wizard = self.env['bxi.fee.payment.wizard'].create({
            'fees_detail_id': detail.id, 'amount': 1000.0,
            'payment_mode': 'cash', 'journal_id': self.cash_journal.id,
        })
        wizard.action_confirm()
        self.assertEqual(detail.collection_status, 'paid')
        self.assertEqual(detail.amount_pending, 0.0)
        self.assertEqual(detail.payment_mode, 'cash')

    def test_payment_wizard_partial_payment_flow(self):
        detail = self._make_detail(amount=1000.0)
        wizard = self.env['bxi.fee.payment.wizard'].create({
            'fees_detail_id': detail.id, 'amount': 400.0,
            'payment_mode': 'upi', 'journal_id': self.cash_journal.id,
        })
        wizard.action_confirm()
        self.assertEqual(detail.collection_status, 'partially_paid')
        self.assertAlmostEqual(detail.amount_pending, 600.0)
