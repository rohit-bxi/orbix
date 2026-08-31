# -*- coding: utf-8 -*-
"""Model-level unit tests for bxi.payment.order, calling its methods
directly (never through the HTTP controller / url_open). The controller
behavior is already covered end-to-end in test_payment.py; here we test
each model method in isolation, one test per method (plus extra tests
for meaningfully distinct branches of a method).
"""
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.bxi_online_fee_payment.models.razorpay_client import RazorpayClient

FAKE_RAZORPAY_ORDER = {'id': 'order_fake_model_1'}


def _fake_create_order(self, amount, currency, receipt):
    return dict(FAKE_RAZORPAY_ORDER)


def _fake_create_order_failure(self, amount, currency, receipt):
    return None


@tagged('post_install', '-at_install')
class TestBxiPaymentOrderModel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_accounting()

        cls.student = cls.env['op.student'].create({
            'first_name': 'Model', 'last_name': 'Payer', 'gr_no': 'PAYM-001', 'gender': 'm',
        })
        cls.student.partner_id.property_account_receivable_id = cls.receivable_account

        cls.product = cls.env['product.product'].create({
            'name': 'Tuition Fee Model', 'lst_price': 1000.0,
            'property_account_income_id': cls.income_account.id, 'taxes_id': [(5, 0, 0)],
        })
        cls.fee_category = cls.env['bxi.fee.category'].create({
            'name': 'Tuition Model', 'code': 'TUIOPM', 'product_id': cls.product.id, 'default_frequency': 'annual',
        })
        cls.structure = cls.env['op.fees.terms'].create({
            'name': 'Model Payment Structure', 'code': 'OPSM01', 'fees_terms': 'fixed_date',
            'line_ids': [(0, 0, {'due_date': fields.Date.today(), 'value': 100.0})],
            'category_line_ids': [(0, 0, {
                'category_id': cls.fee_category.id, 'amount': 1000.0, 'frequency': 'annual',
            })],
            'installment_type': 'one_time', 'first_due_date': fields.Date.today(), 'allow_partial_payment': True,
        })
        cls.structure._sync_category_lines_to_elements()
        cls.detail = cls.env['op.student.fees.details'].create({
            'student_id': cls.student.id,
            'fees_line_id': cls.structure.line_ids[0].id,
            'product_id': cls.product.id,
            'amount': 1000.0,
            'date': fields.Date.today(),
            'state': 'draft',
        })
        cls.detail.get_invoice()
        cls.detail.invoice_id.action_post()

        cls.env['ir.config_parameter'].sudo().set_param(
            'bxi_online_fee_payment.default_journal_id', str(cls.cash_journal.id))

        cls.user = cls.env.ref('base.user_admin')

    @classmethod
    def _setup_accounting(cls):
        company = cls.env.company
        cls.income_account = cls.env['account.account'].search(
            [('account_type', '=', 'income'), ('company_ids', 'in', company.id)], limit=1)
        if not cls.income_account:
            cls.income_account = cls.env['account.account'].create({
                'name': 'Test Income Model', 'code': 'TINC05', 'account_type': 'income',
                'company_ids': [(6, 0, [company.id])],
            })
        cls.receivable_account = cls.env['account.account'].search(
            [('account_type', '=', 'asset_receivable'), ('company_ids', 'in', company.id)], limit=1)
        if not cls.receivable_account:
            cls.receivable_account = cls.env['account.account'].create({
                'name': 'Test Receivable Model', 'code': 'TREC05', 'account_type': 'asset_receivable',
                'reconcile': True, 'company_ids': [(6, 0, [company.id])],
            })
        cls.sale_journal = cls.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', company.id)], limit=1)
        if not cls.sale_journal:
            cls.sale_journal = cls.env['account.journal'].create({
                'name': 'Test Sales Journal Model', 'type': 'sale', 'code': 'TSJ05',
            })
        cls.cash_journal = cls.env['account.journal'].search(
            [('type', '=', 'cash'), ('company_id', '=', company.id)], limit=1)
        if not cls.cash_journal:
            cls.cash_journal = cls.env['account.journal'].create({
                'name': 'Test Cash Journal Model', 'type': 'cash', 'code': 'TCJ05',
            })

    def _new_order(self, amount=500.0):
        return self.env['bxi.payment.order'].sudo().create({
            'fees_detail_id': self.detail.id,
            'amount': amount,
            'user_id': self.user.id,
        })

    # -- _create_for_fee_line -------------------------------------------------

    @patch.object(RazorpayClient, 'create_order', _fake_create_order)
    def test_create_for_fee_line_success(self):
        order = self.env['bxi.payment.order']._create_for_fee_line(self.detail, 500.0, self.user)
        self.assertTrue(order)
        self.assertEqual(order.razorpay_order_id, 'order_fake_model_1')
        self.assertEqual(order.status, 'created')
        self.assertEqual(order.amount, 500.0)
        self.assertEqual(order.fees_detail_id, self.detail)

    def test_create_for_fee_line_zero_amount_raises(self):
        with self.assertRaises(UserError):
            self.env['bxi.payment.order']._create_for_fee_line(self.detail, 0.0, self.user)

    def test_create_for_fee_line_amount_exceeds_pending_raises(self):
        with self.assertRaises(UserError):
            self.env['bxi.payment.order']._create_for_fee_line(self.detail, 999999.0, self.user)

    @patch.object(RazorpayClient, 'create_order', _fake_create_order_failure)
    def test_create_for_fee_line_gateway_failure_marks_order_failed(self):
        order = self.env['bxi.payment.order']._create_for_fee_line(self.detail, 500.0, self.user)
        self.assertIsNone(order)
        created = self.env['bxi.payment.order'].sudo().search(
            [('fees_detail_id', '=', self.detail.id), ('amount', '=', 500.0)], order='id desc', limit=1)
        self.assertEqual(created.status, 'failed')

    # -- _default_journal -----------------------------------------------------

    def test_default_journal_returns_configured_journal(self):
        order = self._new_order()
        self.assertEqual(order._default_journal(), self.cash_journal)

    def test_default_journal_returns_empty_recordset_when_not_configured(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_online_fee_payment.default_journal_id', '')
        try:
            order = self._new_order()
            journal = order._default_journal()
            self.assertFalse(journal)
        finally:
            self.env['ir.config_parameter'].sudo().set_param(
                'bxi_online_fee_payment.default_journal_id', str(self.cash_journal.id))

    # -- _reconcile_payment ----------------------------------------------------

    def test_reconcile_payment_success_marks_paid_and_registers_payment(self):
        order = self._new_order(amount=500.0)
        order.razorpay_order_id = 'order_fake_model_2'
        order.razorpay_payment_id = 'pay_fake_model_2'
        order._reconcile_payment()
        self.assertEqual(order.status, 'paid')
        self.assertAlmostEqual(self.detail.amount_paid, 500.0)

    def test_reconcile_payment_without_configured_journal_raises(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_online_fee_payment.default_journal_id', '')
        try:
            order = self._new_order(amount=500.0)
            order.razorpay_order_id = 'order_fake_model_3'
            order.razorpay_payment_id = 'pay_fake_model_3'
            with self.assertRaises(UserError):
                order._reconcile_payment()
        finally:
            self.env['ir.config_parameter'].sudo().set_param(
                'bxi_online_fee_payment.default_journal_id', str(self.cash_journal.id))

    # -- _mark_paid_from_client -------------------------------------------------

    @patch.object(RazorpayClient, 'verify_payment_signature', lambda self, o, p, s: True)
    def test_mark_paid_from_client_correct_signature_reconciles(self):
        order = self._new_order(amount=500.0)
        order.razorpay_order_id = 'order_fake_model_4'
        result = order._mark_paid_from_client('pay_fake_model_4', 'sig-ok')
        self.assertTrue(result)
        self.assertEqual(order.status, 'paid')
        self.assertEqual(order.razorpay_payment_id, 'pay_fake_model_4')
        self.assertAlmostEqual(self.detail.amount_paid, 500.0)

    @patch.object(RazorpayClient, 'verify_payment_signature', lambda self, o, p, s: False)
    def test_mark_paid_from_client_wrong_signature_marks_failed(self):
        order = self._new_order(amount=500.0)
        order.razorpay_order_id = 'order_fake_model_5'
        result = order._mark_paid_from_client('pay_fake_model_5', 'sig-bad')
        self.assertFalse(result)
        self.assertEqual(order.status, 'failed')

    @patch.object(RazorpayClient, 'verify_payment_signature', lambda self, o, p, s: True)
    def test_mark_paid_from_client_already_paid_is_idempotent(self):
        order = self._new_order(amount=500.0)
        order.razorpay_order_id = 'order_fake_model_6'
        first = order._mark_paid_from_client('pay_fake_model_6', 'sig-ok')
        self.assertTrue(first)
        self.assertAlmostEqual(self.detail.amount_paid, 500.0)

        second = order._mark_paid_from_client('pay_fake_model_6', 'sig-ok')
        self.assertTrue(second)
        self.assertEqual(order.status, 'paid')
        # No double reconciliation - amount paid must not double.
        self.assertAlmostEqual(self.detail.amount_paid, 500.0)

    # -- _mark_paid_from_webhook -------------------------------------------------

    def test_mark_paid_from_webhook_reconciles(self):
        order = self._new_order(amount=500.0)
        order.razorpay_order_id = 'order_fake_model_7'
        result = order._mark_paid_from_webhook('pay_fake_model_7')
        self.assertTrue(result)
        self.assertEqual(order.status, 'paid')
        self.assertEqual(order.razorpay_payment_id, 'pay_fake_model_7')
        self.assertAlmostEqual(self.detail.amount_paid, 500.0)

    def test_mark_paid_from_webhook_already_paid_is_idempotent(self):
        order = self._new_order(amount=500.0)
        order.razorpay_order_id = 'order_fake_model_8'
        first = order._mark_paid_from_webhook('pay_fake_model_8')
        self.assertTrue(first)
        self.assertAlmostEqual(self.detail.amount_paid, 500.0)

        second = order._mark_paid_from_webhook('pay_fake_model_8')
        self.assertTrue(second)
        self.assertEqual(order.status, 'paid')
        # No double reconciliation - amount paid must not double.
        self.assertAlmostEqual(self.detail.amount_paid, 500.0)
