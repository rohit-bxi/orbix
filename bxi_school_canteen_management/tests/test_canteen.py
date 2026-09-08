# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCanteen(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student = cls.env['op.student'].create({
            'first_name': 'Alice',
            'last_name': 'Roe',
            'gr_no': 'CAN-001',
            'gender': 'f',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Veg Sandwich',
            'list_price': 50.0,
            'is_canteen_item': True,
            'available_today': True,
        })
        cls.wallet = cls.env['bxi.canteen.wallet'].create({
            'student_id': cls.student.id,
        })

    def _topup(self, wallet, amount):
        self.env['bxi.canteen.wallet.transaction'].create({
            'wallet_id': wallet.id,
            'transaction_type': 'topup',
            'amount': amount,
            'state': 'posted',
            'payment_method': 'cash',
        })

    def _make_order(self, student, qty=1.0):
        order = self.env['bxi.canteen.order'].create({
            'student_id': student.id,
        })
        self.env['bxi.canteen.order.line'].create({
            'order_id': order.id,
            'product_id': self.product.id,
            'quantity': qty,
            'price_unit': self.product.list_price,
        })
        return order

    def test_patron_mixin_requires_exactly_one(self):
        with self.assertRaises(ValidationError):
            self.env['bxi.canteen.wallet'].create({})

    def test_wallet_balance_computed_from_posted_transactions(self):
        self.assertEqual(self.wallet.balance, 0.0)
        self._topup(self.wallet, 200.0)
        self.assertEqual(self.wallet.balance, 200.0)

    def test_duplicate_wallet_for_same_student_blocked(self):
        with self.assertRaises(ValidationError):
            self.env['bxi.canteen.wallet'].create({'student_id': self.student.id})

    def test_order_total_amount_computed_from_lines(self):
        order = self._make_order(self.student, qty=2.0)
        self.assertEqual(order.total_amount, 100.0)

    def test_order_confirm_debits_wallet(self):
        self._topup(self.wallet, 200.0)
        order = self._make_order(self.student, qty=2.0)
        order.action_confirm()
        self.assertEqual(order.state, 'confirmed')
        self.assertEqual(self.wallet.balance, 100.0)
        self.assertTrue(order.debit_transaction_id)

    def test_order_confirm_blocked_on_insufficient_balance(self):
        order = self._make_order(self.student, qty=5.0)
        with self.assertRaises(ValidationError):
            order.action_confirm()
        self.assertEqual(order.state, 'draft')

    def test_order_state_workflow_sequence(self):
        self._topup(self.wallet, 200.0)
        order = self._make_order(self.student, qty=1.0)
        order.action_confirm()
        order.action_preparing()
        self.assertEqual(order.state, 'preparing')
        order.action_ready()
        self.assertEqual(order.state, 'ready')
        order.action_served()
        self.assertEqual(order.state, 'served')

    def test_cannot_skip_workflow_states(self):
        self._topup(self.wallet, 200.0)
        order = self._make_order(self.student, qty=1.0)
        with self.assertRaises(ValidationError):
            order.action_preparing()

    def test_cancel_confirmed_order_refunds_wallet(self):
        self._topup(self.wallet, 200.0)
        order = self._make_order(self.student, qty=2.0)
        order.action_confirm()
        self.assertEqual(self.wallet.balance, 100.0)
        order.cancel_reason = 'Changed mind'
        order.action_cancel()
        self.assertEqual(order.state, 'cancelled')
        self.assertEqual(self.wallet.balance, 200.0)

    def test_wallet_transaction_amount_sign_constraints(self):
        with self.assertRaises(ValidationError):
            self.env['bxi.canteen.wallet.transaction'].create({
                'wallet_id': self.wallet.id,
                'transaction_type': 'topup',
                'amount': -50.0,
                'state': 'posted',
            })
        with self.assertRaises(ValidationError):
            self.env['bxi.canteen.wallet.transaction'].create({
                'wallet_id': self.wallet.id,
                'transaction_type': 'order_payment',
                'amount': 50.0,
                'state': 'posted',
            })

    def test_low_balance_flag(self):
        self.wallet.low_balance_threshold = 100.0
        self._topup(self.wallet, 50.0)
        self.assertTrue(self.wallet.is_low_balance)
        self._topup(self.wallet, 100.0)
        self.assertFalse(self.wallet.is_low_balance)
