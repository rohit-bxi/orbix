# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import HttpCase


class ApiSupportHttpCase(HttpCase):
    """Shared fixtures for bxi_api_support HTTP tests: an income/receivable
    account pair and sale/cash journals (same setup bxi_fee_exemption_management's
    and bxi_student_refund_management's own test suites use), plus helpers to
    create a student with a posted invoice so the fee/exemption/refund/
    scholarship money fields compute against something real.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_accounting()

    @classmethod
    def _setup_accounting(cls):
        company = cls.env.company
        cls.income_account = cls.env['account.account'].search(
            [('account_type', '=', 'income'), ('company_ids', 'in', company.id)], limit=1)
        if not cls.income_account:
            cls.income_account = cls.env['account.account'].create({
                'name': 'API Support Test Income', 'code': 'APIINC01', 'account_type': 'income',
                'company_ids': [(6, 0, [company.id])],
            })
        cls.receivable_account = cls.env['account.account'].search(
            [('account_type', '=', 'asset_receivable'), ('company_ids', 'in', company.id)], limit=1)
        if not cls.receivable_account:
            cls.receivable_account = cls.env['account.account'].create({
                'name': 'API Support Test Receivable', 'code': 'APIREC01', 'account_type': 'asset_receivable',
                'reconcile': True, 'company_ids': [(6, 0, [company.id])],
            })
        cls.sale_journal = cls.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', company.id)], limit=1)
        if not cls.sale_journal:
            cls.sale_journal = cls.env['account.journal'].create({
                'name': 'API Support Test Sales Journal', 'type': 'sale', 'code': 'APISJ1',
            })
        cls.cash_journal = cls.env['account.journal'].search(
            [('type', '=', 'cash'), ('company_id', '=', company.id)], limit=1)
        if not cls.cash_journal:
            cls.cash_journal = cls.env['account.journal'].create({
                'name': 'API Support Test Cash Journal', 'type': 'cash', 'code': 'APICJ1',
            })

    @classmethod
    def _create_student(cls, gr_no, first_name='Test', last_name='Student', gender='m', user=None):
        vals = {'first_name': first_name, 'last_name': last_name, 'gr_no': gr_no, 'gender': gender}
        if user:
            vals['user_id'] = user.id
        student = cls.env['op.student'].create(vals)
        student.partner_id.property_account_receivable_id = cls.receivable_account
        return student

    @classmethod
    def _create_posted_invoice(cls, student, total, paid=0.0):
        invoice = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': student.partner_id.id,
            'journal_id': cls.sale_journal.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Test Fee', 'account_id': cls.income_account.id,
                'price_unit': total, 'quantity': 1.0, 'tax_ids': [(5, 0, 0)],
            })],
        })
        invoice.action_post()
        if paid:
            register = cls.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=invoice.ids,
            ).create({'amount': paid, 'journal_id': cls.cash_journal.id})
            register.action_create_payments()
        return invoice

    def _headers(self, login, password):
        resp = self.url_open('/api/v1/auth/login', json={'login': login, 'password': password})
        return {'Authorization': f'Bearer {resp.json()["data"]["token"]}'}
