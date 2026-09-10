# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestScholarshipDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student = cls.env['op.student'].create({
            'first_name': 'Dash', 'last_name': 'Board',
            'gr_no': 'SCH-DASH-001', 'gender': 'f',
        })
        cls.academic_year = cls.env['op.academic.year'].create({
            'name': 'AY Dashboard Test',
            'start_date': '2026-01-01', 'end_date': '2026-12-31',
        })
        cls.program = cls.env['bxi.scholarship.program'].create({
            'name': 'Dashboard Merit Program',
            'scholarship_type': 'merit',
            'budget_amount': 10000.0,
        })
        cls.scholarship = cls.env['bxi.student.scholarship'].create({
            'student_id': cls.student.id,
            'program_id': cls.program.id,
            'scholarship_type': 'merit',
            'academic_year_id': cls.academic_year.id,
            'coverage_type': 'fixed_amount',
            'fixed_amount': 500.0,
            'valid_from': '2026-01-01', 'valid_until': '2026-12-31',
        })
        cls.env['bxi.student.scholarship.fee.line'].create({
            'scholarship_id': cls.scholarship.id,
            'fee_category_id': cls.env['product.product'].create({
                'name': 'Dashboard Tuition Fee', 'lst_price': 1000.0,
            }).id,
            'total_amount': 1000.0,
        })
        cls.scholarship.action_submit()
        cls.scholarship.action_approve()

    def test_program_budget_usage_computed(self):
        self.assertEqual(self.program.recipient_count, 1)
        self.assertEqual(self.program.amount_disbursed, self.scholarship.scholarship_amount)
        self.assertEqual(self.program.budget_utilization, self.program.amount_disbursed / 10000.0 * 100.0)

    def test_get_dashboard_data_structure(self):
        """get_dashboard_data() must run cleanly against whatever data is in
        the database and always return every top-level section the client
        action reads, each with the keys it expects."""
        data = self.env['bxi.scholarship.dashboard'].get_dashboard_data()

        self.assertIn('kpis', data)
        self.assertIn('student_list', data)
        self.assertIn('charts', data)
        self.assertIn('top_programs', data)
        self.assertIn('stats', data)
        self.assertIn('recent_activity', data)

        expected_kpis = {
            'total_scholarships_active', 'total_recipients', 'total_amount_disbursed', 'budget_utilization',
        }
        self.assertEqual(expected_kpis, set(data['kpis'].keys()))
        for kpi in data['kpis'].values():
            self.assertIn('value', kpi)

        expected_charts = {
            'type_distribution', 'class_wise_recipients', 'monthly_disbursement_trend', 'budget_allocation',
        }
        self.assertEqual(expected_charts, set(data['charts'].keys()))
        self.assertEqual(6, len(data['charts']['monthly_disbursement_trend']['labels']))

        expected_stats = {'average_per_student', 'highest_amount', 'applications_pending'}
        self.assertEqual(expected_stats, set(data['stats'].keys()))

        self.assertIsInstance(data['student_list'], list)
        self.assertIsInstance(data['top_programs'], list)
        self.assertIsInstance(data['recent_activity'], list)

    def test_dashboard_reflects_approved_scholarship(self):
        data = self.env['bxi.scholarship.dashboard'].get_dashboard_data()
        self.assertEqual(data['kpis']['total_recipients']['value'], 1)
        self.assertEqual(data['kpis']['total_amount_disbursed']['value'], self.scholarship.scholarship_amount)
        self.assertTrue(any(p['name'] == self.program.name for p in data['top_programs']))

    def test_export_full_report_action(self):
        # Just confirm the report reference resolves and the call executes
        # cleanly; the exact returned action shape depends on whether the
        # company has an external report layout configured.
        action = self.env['bxi.scholarship.dashboard'].action_export_full_report()
        self.assertIsInstance(action, dict)
