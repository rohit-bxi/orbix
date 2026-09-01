from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFeeExemption(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_accounting()

        cls.student = cls.env['op.student'].create({
            'first_name': 'Exempt', 'last_name': 'Student', 'gr_no': 'EXM-001', 'gender': 'f',
        })
        cls.student.partner_id.property_account_receivable_id = cls.receivable_account

        cls.tuition_product = cls.env['product.product'].create({
            'name': 'Tuition Fee', 'lst_price': 1000.0,
            'property_account_income_id': cls.income_account.id,
            'taxes_id': [(5, 0, 0)],
        })
        cls.transport_product = cls.env['product.product'].create({
            'name': 'Transport Fee', 'lst_price': 500.0,
            'property_account_income_id': cls.income_account.id,
            'taxes_id': [(5, 0, 0)],
        })

        # Total fee amount 2000, paid 1500 => pending 500 for the student.
        cls._create_posted_invoice(cls.student, 2000.0, 1500.0)

    @classmethod
    def _setup_accounting(cls):
        company = cls.env.company
        cls.income_account = cls.env['account.account'].search(
            [('account_type', '=', 'income'), ('company_ids', 'in', company.id)], limit=1)
        if not cls.income_account:
            cls.income_account = cls.env['account.account'].create({
                'name': 'Test Income', 'code': 'TINC02', 'account_type': 'income',
                'company_ids': [(6, 0, [company.id])],
            })
        cls.receivable_account = cls.env['account.account'].search(
            [('account_type', '=', 'asset_receivable'), ('company_ids', 'in', company.id)], limit=1)
        if not cls.receivable_account:
            cls.receivable_account = cls.env['account.account'].create({
                'name': 'Test Receivable', 'code': 'TREC02', 'account_type': 'asset_receivable',
                'reconcile': True, 'company_ids': [(6, 0, [company.id])],
            })
        cls.sale_journal = cls.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', company.id)], limit=1)
        if not cls.sale_journal:
            cls.sale_journal = cls.env['account.journal'].create({
                'name': 'Test Sales Journal', 'type': 'sale', 'code': 'TSJ02',
            })
        cls.cash_journal = cls.env['account.journal'].search(
            [('type', '=', 'cash'), ('company_id', '=', company.id)], limit=1)
        if not cls.cash_journal:
            cls.cash_journal = cls.env['account.journal'].create({
                'name': 'Test Cash Journal', 'type': 'cash', 'code': 'TCJ02',
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

    def _make_exemption(self, **kwargs):
        vals = {
            'student_id': self.student.id,
            'exemption_type': 'financial_hardship',
            'category': 'partial_exemption',
            'exemption_method': 'fixed_amount',
            'fixed_amount': 200.0,
            'valid_from': fields.Date.today(),
            'valid_until': fields.Date.today() + timedelta(days=180),
            'fee_line_ids': [
                (0, 0, {'fee_category_id': self.tuition_product.id, 'total_amount': 1000.0}),
                (0, 0, {'fee_category_id': self.transport_product.id, 'total_amount': 500.0}),
            ],
        }
        vals.update(kwargs)
        return self.env['bxi.fee.exemption'].create(vals)

    # -- Fee Exemption: money math ----------------------------------------------

    def test_fixed_amount_split_across_lines(self):
        exemption = self._make_exemption(exemption_method='fixed_amount', fixed_amount=300.0)
        # Split evenly across the 2 in-scope lines -> 150 each.
        self.assertAlmostEqual(exemption.fee_line_ids[0].exemption_applied, 150.0)
        self.assertAlmostEqual(exemption.fee_line_ids[1].exemption_applied, 150.0)
        self.assertAlmostEqual(exemption.exemption_amount, 300.0)
        self.assertAlmostEqual(exemption.net_payable_amount, 1200.0)

    def test_percentage_method_applies_per_line(self):
        exemption = self._make_exemption(exemption_method='percentage', coverage_percentage=20.0)
        self.assertAlmostEqual(exemption.fee_line_ids[0].exemption_applied, 200.0)  # 20% of 1000
        self.assertAlmostEqual(exemption.fee_line_ids[1].exemption_applied, 100.0)  # 20% of 500
        self.assertAlmostEqual(exemption.total_fee_amount, 1500.0)
        self.assertAlmostEqual(exemption.exemption_amount, 300.0)

    def test_max_exemption_amount_caps_header_total(self):
        exemption = self._make_exemption(
            exemption_method='percentage', coverage_percentage=50.0, max_exemption_amount=100.0)
        # Uncapped would be 750 (50% of 1500), but header cap limits exemption_amount to 100.
        self.assertAlmostEqual(exemption.exemption_amount, 100.0)
        self.assertAlmostEqual(exemption.net_payable_amount, 1400.0)

    def test_scope_specific_excludes_other_categories(self):
        exemption = self._make_exemption(
            exemption_method='fixed_amount', fixed_amount=100.0,
            fee_category_scope='specific',
            applicable_fee_category_ids=[(6, 0, [self.tuition_product.id])])
        tuition_line = exemption.fee_line_ids.filtered(lambda l: l.fee_category_id == self.tuition_product)
        transport_line = exemption.fee_line_ids.filtered(lambda l: l.fee_category_id == self.transport_product)
        self.assertAlmostEqual(tuition_line.exemption_applied, 100.0)
        self.assertAlmostEqual(transport_line.exemption_applied, 0.0)

    def test_exemption_cannot_exceed_line_total(self):
        exemption = self._make_exemption(exemption_method='fixed_amount', fixed_amount=5000.0)
        for line in exemption.fee_line_ids:
            self.assertLessEqual(line.exemption_applied, line.total_amount)
            self.assertGreaterEqual(line.net_amount, 0.0)

    def test_duplicate_fee_category_line_blocked(self):
        exemption = self._make_exemption()
        with self.assertRaises(ValidationError):
            self.env['bxi.fee.exemption.fee.line'].create({
                'exemption_id': exemption.id,
                'fee_category_id': self.tuition_product.id,
                'total_amount': 100.0,
            })

    def test_percentage_out_of_range_blocked(self):
        with self.assertRaises(ValidationError):
            self._make_exemption(exemption_method='percentage', coverage_percentage=150.0)

    def test_negative_fixed_amount_blocked(self):
        with self.assertRaises(ValidationError):
            self._make_exemption(exemption_method='fixed_amount', fixed_amount=-10.0)

    def test_invalid_validity_period_blocked(self):
        with self.assertRaises(ValidationError):
            self._make_exemption(
                valid_from=fields.Date.today(),
                valid_until=fields.Date.today() - timedelta(days=1))

    def test_approval_workflow_transitions(self):
        exemption = self._make_exemption()
        self.assertEqual(exemption.approval_status, 'draft')
        exemption.action_submit()
        self.assertEqual(exemption.approval_status, 'pending')
        exemption.action_approve()
        self.assertEqual(exemption.approval_status, 'approved')
        self.assertEqual(exemption.approved_by, self.env.user)
        self.assertTrue(exemption.approval_date)
        exemption.action_reset_to_draft()
        self.assertEqual(exemption.approval_status, 'draft')
        self.assertFalse(exemption.approved_by)

    # -- Fee Exemption Request ----------------------------------------------------

    def _make_request(self, **kwargs):
        vals = {
            'student_id': self.student.id,
            'exemption_type': 'merit_based',
            'request_value_type': 'amount',
            'requested_amount': 300.0,
            'reason': 'Excellent academic performance',
        }
        vals.update(kwargs)
        return self.env['bxi.fee.exemption.request'].create(vals)

    def test_request_payment_summary_matches_invoice(self):
        request = self._make_request()
        self.assertAlmostEqual(request.total_fee_amount, 2000.0)
        self.assertAlmostEqual(request.total_paid_amount, 1500.0)
        self.assertAlmostEqual(request.pending_amount, 500.0)

    def test_request_requires_positive_amount(self):
        with self.assertRaises(ValidationError):
            self._make_request(request_value_type='amount', requested_amount=0.0)

    def test_request_percentage_must_be_in_range(self):
        with self.assertRaises(ValidationError):
            self._make_request(request_value_type='percentage', requested_percentage=0.0)

    def test_request_status_guard_blocks_out_of_order_review(self):
        request = self._make_request()
        with self.assertRaises(UserError):
            request.action_start_review()

    def test_request_full_lifecycle_to_approve_wizard(self):
        request = self._make_request()
        request.action_submit()
        self.assertEqual(request.status, 'pending_review')
        request.action_start_review()
        self.assertEqual(request.status, 'under_review')

        action = request.action_open_approve_wizard()
        wizard = self.env['bxi.fee.exemption.approve.wizard'].create({
            'request_id': request.id,
            'approval_type': 'full_approval',
            'exemption_method': 'fixed_amount',
            'approved_amount': 300.0,
            'valid_from': fields.Date.today(),
            'valid_until': fields.Date.today() + timedelta(days=90),
        })
        self.assertEqual(wizard.current_pending_amount, 500.0)
        self.assertAlmostEqual(wizard.new_pending_amount, 200.0)
        wizard.action_confirm_approve()

        self.assertEqual(request.status, 'approved')
        self.assertTrue(request.exemption_id)
        self.assertEqual(request.exemption_id.approval_status, 'approved')
        self.assertEqual(request.exemption_id.fixed_amount, 300.0)

    def test_approve_wizard_onchange_maps_amount_request_value_type(self):
        # request_value_type uses 'amount'/'percentage'; exemption_method uses
        # 'fixed_amount'/'percentage' - the onchange must translate, not copy raw.
        request = self._make_request(request_value_type='amount', requested_amount=300.0)
        request.action_submit()
        request.action_start_review()

        wizard = self.env['bxi.fee.exemption.approve.wizard'].new({'request_id': request.id})
        wizard.approval_type = 'full_approval'
        wizard._onchange_approval_type()
        self.assertEqual(wizard.exemption_method, 'fixed_amount')
        self.assertAlmostEqual(wizard.approved_amount, 300.0)

    def test_approve_wizard_onchange_maps_percentage_request_value_type(self):
        request = self._make_request(
            request_value_type='percentage', requested_amount=0.0, requested_percentage=25.0)
        request.action_submit()
        request.action_start_review()

        wizard = self.env['bxi.fee.exemption.approve.wizard'].new({'request_id': request.id})
        wizard.approval_type = 'full_approval'
        wizard._onchange_approval_type()
        self.assertEqual(wizard.exemption_method, 'percentage')

    def test_approve_wizard_requires_positive_amount(self):
        request = self._make_request()
        request.action_submit()
        with self.assertRaises(ValidationError):
            self.env['bxi.fee.exemption.approve.wizard'].create({
                'request_id': request.id,
                'approval_type': 'full_approval',
                'exemption_method': 'fixed_amount',
                'approved_amount': 0.0,
                'valid_from': fields.Date.today(),
                'valid_until': fields.Date.today() + timedelta(days=90),
            })

    def test_reject_wizard_requires_typed_confirmation(self):
        request = self._make_request()
        request.action_submit()
        wizard = self.env['bxi.fee.exemption.reject.wizard'].create({
            'request_id': request.id,
            'rejection_reason_category': 'not_eligible',
            'detailed_rejection_reason': 'Does not meet income threshold.',
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm_reject()
        wizard.confirmation_text = 'REJECT'
        wizard.action_confirm_reject()
        self.assertEqual(request.status, 'rejected')
        self.assertEqual(request.rejection_reason_category, 'not_eligible')

    def test_delete_wizard_requires_all_confirmations(self):
        exemption = self._make_exemption()
        wizard = self.env['bxi.fee.exemption.delete.wizard'].create({
            'exemption_id': exemption.id,
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm_delete()
        wizard.write({
            'confirmation_text': 'DELETE',
            'understand_permanent': True,
            'notify_of_change': True,
        })
        wizard.action_confirm_delete()
        self.assertFalse(exemption.exists())
