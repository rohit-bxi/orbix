# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestUniform(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student = cls.env['op.student'].create({
            'first_name': 'Nora',
            'last_name': 'Fields',
            'gr_no': 'UNI-001',
            'gender': 'f',
        })
        income_account = cls.env['account.account'].search([
            ('account_type', '=', 'income'),
        ], limit=1)
        cls.shirt = cls.env['product.product'].create({
            'name': 'School Shirt - M',
            'list_price': 300.0,
            'is_uniform_item': True,
            'property_account_income_id': income_account.id,
        })
        cls.trouser = cls.env['product.product'].create({
            'name': 'School Trouser - M',
            'list_price': 400.0,
            'is_uniform_item': True,
            'property_account_income_id': income_account.id,
        })
        company = cls.env.company
        cls.cash_journal = cls.env['account.journal'].search(
            [('type', '=', 'cash'), ('company_id', '=', company.id)], limit=1)
        if not cls.cash_journal:
            cls.cash_journal = cls.env['account.journal'].create({
                'name': 'Test Cash Journal', 'type': 'cash', 'code': 'TCJ03',
            })

    def _pay_invoice(self, order):
        invoice = order.invoice_id
        invoice.action_post()
        register = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids,
        ).create({'journal_id': self.cash_journal.id})
        register.action_create_payments()

    def _receive_stock(self, product, qty):
        stock = self.env['bxi.uniform.stock']._get_or_create(product.id)
        self.env['bxi.uniform.stock.move'].create({
            'stock_id': stock.id,
            'move_type': 'receipt',
            'quantity': qty,
            'state': 'posted',
        })
        return stock

    def _make_order(self, student, lines):
        order = self.env['bxi.uniform.order'].create({
            'type': 'student',
            'student_id': student.id,
        })
        for product, qty in lines:
            self.env['bxi.uniform.order.line'].create({
                'order_id': order.id,
                'product_id': product.id,
                'quantity': qty,
                'price_unit': product.list_price,
            })
        return order

    def test_patron_mixin_requires_exactly_one(self):
        with self.assertRaises(ValidationError):
            self.env['bxi.uniform.order'].create({'type': 'student'})

    def test_stock_quantity_computed_from_posted_moves(self):
        stock = self._receive_stock(self.shirt, 10)
        self.assertEqual(stock.quantity_on_hand, 10)

    def test_stock_unique_per_product(self):
        self.env['bxi.uniform.stock'].create({'product_id': self.shirt.id})
        with mute_logger('odoo.sql_db'), self.assertRaises(Exception):
            self.env['bxi.uniform.stock'].create({'product_id': self.shirt.id})

    def test_stock_move_quantity_sign_constraints(self):
        stock = self.env['bxi.uniform.stock']._get_or_create(self.shirt.id)
        with self.assertRaises(ValidationError):
            self.env['bxi.uniform.stock.move'].create({
                'stock_id': stock.id,
                'move_type': 'receipt',
                'quantity': -5,
                'state': 'posted',
            })
        with self.assertRaises(ValidationError):
            self.env['bxi.uniform.stock.move'].create({
                'stock_id': stock.id,
                'move_type': 'issue',
                'quantity': 5,
                'state': 'posted',
            })

    def test_order_total_amount_computed_from_lines(self):
        order = self._make_order(self.student, [(self.shirt, 2), (self.trouser, 1)])
        self.assertEqual(order.total_amount, 1000.0)

    def test_confirm_requires_lines(self):
        order = self.env['bxi.uniform.order'].create({
            'type': 'student',
            'student_id': self.student.id,
        })
        with self.assertRaises(ValidationError):
            order.action_confirm()

    def test_confirm_creates_invoice(self):
        order = self._make_order(self.student, [(self.shirt, 1)])
        order.action_confirm()
        self.assertEqual(order.state, 'confirmed')
        self.assertTrue(order.invoice_id)
        self.assertEqual(order.invoice_id.move_type, 'out_invoice')

    def test_issue_blocked_when_insufficient_stock(self):
        order = self._make_order(self.student, [(self.shirt, 5)])
        order.action_confirm()
        self._pay_invoice(order)
        with self.assertRaises(ValidationError):
            order.action_mark_issued()
        self.assertEqual(order.state, 'confirmed')

    def test_issue_debits_stock_and_sets_state(self):
        self._receive_stock(self.shirt, 10)
        order = self._make_order(self.student, [(self.shirt, 3)])
        order.action_confirm()
        self._pay_invoice(order)
        order.action_mark_issued()
        self.assertEqual(order.state, 'issued')
        stock = self.env['bxi.uniform.stock']._get_or_create(self.shirt.id)
        self.assertEqual(stock.quantity_on_hand, 7)
        self.assertTrue(order.issued_by)

    def test_force_issue_requires_manager_group(self):
        order = self._make_order(self.student, [(self.shirt, 5)])
        order.action_confirm()
        with self.assertRaises(AccessError):
            order.action_force_issue()

    def test_cancel_issued_order_returns_stock(self):
        self._receive_stock(self.shirt, 10)
        order = self._make_order(self.student, [(self.shirt, 3)])
        order.action_confirm()
        self._pay_invoice(order)
        order.action_mark_issued()
        stock = self.env['bxi.uniform.stock']._get_or_create(self.shirt.id)
        self.assertEqual(stock.quantity_on_hand, 7)
        order.cancel_reason = 'Wrong size ordered'
        order.action_cancel()
        self.assertEqual(order.state, 'cancelled')
        self.assertEqual(stock.quantity_on_hand, 10)

    def test_exchange_wizard_swaps_product_and_moves_stock(self):
        # A size exchange rewrites the invoice line's price, which is only
        # allowed while that invoice is still a draft (see action_exchange
        # below); action_mark_issued requires the invoice to already be
        # paid (hence posted), so exercise the still-draft-invoice path via
        # action_force_issue instead, as a Uniform Manager would.
        self.env.user.write({'group_ids': [
            (4, self.env.ref('bxi_uniform_management.group_uniform_manager').id)]})
        self._receive_stock(self.shirt, 5)
        self._receive_stock(self.trouser, 5)
        order = self._make_order(self.student, [(self.shirt, 2)])
        order.action_confirm()
        order.action_force_issue()
        line = order.order_line_ids[0]
        wizard = self.env['bxi.uniform.exchange.wizard'].create({
            'order_line_id': line.id,
            'new_product_id': self.trouser.id,
        })
        wizard.action_exchange()
        self.assertEqual(line.product_id, self.trouser)
        shirt_stock = self.env['bxi.uniform.stock']._get_or_create(self.shirt.id)
        trouser_stock = self.env['bxi.uniform.stock']._get_or_create(self.trouser.id)
        self.assertEqual(shirt_stock.quantity_on_hand, 5)
        self.assertEqual(trouser_stock.quantity_on_hand, 3)

    def test_exchange_wizard_same_product_blocked(self):
        self._receive_stock(self.shirt, 5)
        order = self._make_order(self.student, [(self.shirt, 2)])
        order.action_confirm()
        self._pay_invoice(order)
        order.action_mark_issued()
        line = order.order_line_ids[0]
        wizard = self.env['bxi.uniform.exchange.wizard'].create({
            'order_line_id': line.id,
            'new_product_id': self.shirt.id,
        })
        with self.assertRaises(ValidationError):
            wizard.action_exchange()

    def test_exchange_wizard_blocked_on_insufficient_new_stock(self):
        self._receive_stock(self.shirt, 5)
        self._receive_stock(self.trouser, 1)
        order = self._make_order(self.student, [(self.shirt, 2)])
        order.action_confirm()
        self._pay_invoice(order)
        order.action_mark_issued()
        line = order.order_line_ids[0]
        wizard = self.env['bxi.uniform.exchange.wizard'].create({
            'order_line_id': line.id,
            'new_product_id': self.trouser.id,
        })
        with self.assertRaises(UserError):
            wizard.action_exchange()

    def test_policy_unique_per_course_gender_season(self):
        course = self.env['op.course'].create({'name': 'Grade 5', 'code': 'G5'})
        self.env['bxi.uniform.policy'].create({
            'course_id': course.id,
            'gender': 'unisex',
            'season': 'all_season',
        })
        with mute_logger('odoo.sql_db'), self.assertRaises(Exception):
            self.env['bxi.uniform.policy'].create({
                'course_id': course.id,
                'gender': 'unisex',
                'season': 'all_season',
            })
