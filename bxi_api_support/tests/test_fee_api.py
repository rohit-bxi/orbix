# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportFee(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fee_staff_user = mail_new_test_user(
            cls.env, login='fee_api_staff',
            groups='base.group_user,openeducat_fees.group_openeducat_fees_user',
            password='FeeStaffPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='fee_api_other', groups='base.group_user', password='OtherPass1!')
        cls.student_user = mail_new_test_user(
            cls.env, login='fee_api_student', groups='base.group_user', password='StudentPass1!')
        cls.student = cls._create_student('FEEAPI-001', user=cls.student_user)

        cls.product = cls.env['product.product'].create({
            'name': 'API Tuition Fee', 'lst_price': 1000.0,
            'property_account_income_id': cls.income_account.id,
            'taxes_id': [(5, 0, 0)],
        })
        cls.fee_category = cls.env['bxi.fee.category'].create({
            'name': 'API Tuition', 'code': 'API-TUI', 'product_id': cls.product.id, 'default_frequency': 'annual',
        })
        cls.structure = cls.env['op.fees.terms'].create({
            'name': 'API Fee Structure', 'code': 'API-SFS001', 'fees_terms': 'fixed_date',
            'line_ids': [(0, 0, {'due_date': fields.Date.today(), 'value': 100.0})],
            'category_line_ids': [(0, 0, {
                'category_id': cls.fee_category.id, 'amount': 1000.0, 'frequency': 'annual'})],
            'installment_type': 'one_time', 'first_due_date': fields.Date.today(),
            'allow_partial_payment': True,
        })
        cls.structure._sync_category_lines_to_elements()
        cls.detail = cls.env['op.student.fees.details'].create({
            'student_id': cls.student.id, 'fees_line_id': cls.structure.line_ids[0].id,
            'product_id': cls.product.id, 'amount': 1000.0, 'discount': 0.0,
            'date': fields.Date.today(), 'state': 'draft',
        })

    def test_list_structures_requires_auth(self):
        self.assertEqual(self.url_open('/api/v1/fees/structures').status_code, 401)

    def test_list_structures_forbidden_for_non_staff(self):
        resp = self.url_open('/api/v1/fees/structures', headers=self._headers('fee_api_other', 'OtherPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_list_structures_visible_to_fee_staff(self):
        resp = self.url_open('/api/v1/fees/structures', headers=self._headers('fee_api_staff', 'FeeStaffPass1!'))
        self.assertEqual(resp.status_code, 200)
        names = [s['name'] for s in resp.json()['data']['structures']]
        self.assertIn('API Fee Structure', names)

    def test_activate_then_deactivate_structure(self):
        headers = self._headers('fee_api_staff', 'FeeStaffPass1!')
        activate = self.url_open(
            f'/api/v1/fees/structures/{self.structure.id}/activate', headers=headers, method='POST')
        self.assertEqual(activate.status_code, 200)
        self.assertEqual(activate.json()['data']['state'], 'active')

        missing_ack = self.url_open(
            f'/api/v1/fees/structures/{self.structure.id}/deactivate', headers=headers, json={}, method='POST')
        self.assertEqual(missing_ack.status_code, 400)

        deactivate = self.url_open(
            f'/api/v1/fees/structures/{self.structure.id}/deactivate', headers=headers,
            json={'ack_impact': True, 'ack_reviewed': True})
        self.assertEqual(deactivate.status_code, 200)
        self.assertEqual(deactivate.json()['data']['state'], 'inactive')

    def test_non_staff_cannot_activate_structure(self):
        resp = self.url_open(
            f'/api/v1/fees/structures/{self.structure.id}/activate',
            headers=self._headers('fee_api_other', 'OtherPass1!'), method='POST')
        self.assertEqual(resp.status_code, 403)

    def test_student_can_see_own_fee_details(self):
        resp = self.url_open(
            f'/api/v1/fees/students/{self.student.id}/details',
            headers=self._headers('fee_api_student', 'StudentPass1!'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['data']['details']), 1)

    def test_unrelated_user_cannot_see_student_fee_details(self):
        resp = self.url_open(
            f'/api/v1/fees/students/{self.student.id}/details',
            headers=self._headers('fee_api_other', 'OtherPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_get_fee_detail_not_found(self):
        resp = self.url_open(
            '/api/v1/fees/details/999999', headers=self._headers('fee_api_staff', 'FeeStaffPass1!'))
        self.assertEqual(resp.status_code, 404)

    def test_pay_fee_detail_full_payment(self):
        headers = self._headers('fee_api_staff', 'FeeStaffPass1!')
        resp = self.url_open(
            f'/api/v1/fees/details/{self.detail.id}/pay', headers=headers,
            json={'amount': 1000.0, 'journal_id': self.cash_journal.id, 'payment_mode': 'cash'})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()['data']
        self.assertEqual(body['collection_status'], 'paid')
        self.assertEqual(body['amount_pending'], 0.0)

    def test_pay_fee_detail_requires_staff(self):
        resp = self.url_open(
            f'/api/v1/fees/details/{self.detail.id}/pay',
            headers=self._headers('fee_api_other', 'OtherPass1!'),
            json={'amount': 1000.0, 'journal_id': self.cash_journal.id})
        self.assertEqual(resp.status_code, 403)

    def test_pay_fee_detail_missing_journal_rejected(self):
        resp = self.url_open(
            f'/api/v1/fees/details/{self.detail.id}/pay',
            headers=self._headers('fee_api_staff', 'FeeStaffPass1!'), json={'amount': 1000.0})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_journal_id')

    def test_pay_fee_detail_over_pending_amount_rejected(self):
        resp = self.url_open(
            f'/api/v1/fees/details/{self.detail.id}/pay',
            headers=self._headers('fee_api_staff', 'FeeStaffPass1!'),
            json={'amount': 5000.0, 'journal_id': self.cash_journal.id})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_transition')
