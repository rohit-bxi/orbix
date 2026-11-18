# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFeeDashboard(TransactionCase):

    def test_get_dashboard_data_structure(self):
        """get_dashboard_data() must run cleanly against whatever data is in
        the database and always return the three top-level sections the
        client action reads, each with every key it expects."""
        data = self.env['bxi.fee.dashboard'].get_dashboard_data()

        self.assertIn('kpis', data)
        self.assertIn('charts', data)
        self.assertIn('recent_activity', data)

        expected_kpis = {
            'total_fees_collected', 'pending_payments', 'total_refunds', 'scholarships',
            'manual_approvals', 'online_payments', 'receipts_generated', 'collection_efficiency',
        }
        self.assertEqual(expected_kpis, set(data['kpis'].keys()))
        for kpi in data['kpis'].values():
            self.assertIn('value', kpi)
            self.assertIn('change', kpi)

        expected_charts = {
            'online_vs_offline', 'monthly_collection_trend', 'scholarship_distribution', 'refund_trends',
        }
        self.assertEqual(expected_charts, set(data['charts'].keys()))
        self.assertEqual(6, len(data['charts']['monthly_collection_trend']['labels']))
        self.assertEqual(6, len(data['charts']['refund_trends']['labels']))

        self.assertIsInstance(data['recent_activity'], list)
        self.assertLessEqual(len(data['recent_activity']), 8)

    def _dashboard(self):
        return self.env['bxi.fee.dashboard']

    def test_pct_change(self):
        dashboard = self._dashboard()
        self.assertEqual(dashboard._pct_change(10, 0), 100.0)
        self.assertEqual(dashboard._pct_change(0, 0), 0.0)
        self.assertEqual(dashboard._pct_change(150, 100), 50.0)
        self.assertEqual(dashboard._pct_change(50, 100), -50.0)

    def test_month_bounds(self):
        start, end = self._dashboard()._month_bounds(0)
        today = fields.Date.context_today(self._dashboard())
        self.assertEqual(start, today.replace(day=1))
        self.assertLessEqual(start, today)
        self.assertGreaterEqual(end, today)
        self.assertEqual((end + timedelta(days=1)).day, 1)
        previous_start, previous_end = self._dashboard()._month_bounds(1)
        self.assertEqual(previous_end + timedelta(days=1), start)

    def _student(self, code):
        return self.env['op.student'].create({'first_name': 'Dash', 'last_name': code, 'gr_no': code, 'gender': 'm'})

    def test_exemption_request_counts_as_manual_approval_and_activity(self):
        before = self._dashboard().get_dashboard_data()['kpis']['manual_approvals']['value']
        request = self.env['bxi.fee.exemption.request'].create({
            'student_id': self._student('FDASH-1').id, 'exemption_type': 'financial_hardship',
            'request_value_type': 'amount', 'requested_amount': 100.0, 'reason': 'Dashboard test'})
        request.action_submit()
        data = self._dashboard().get_dashboard_data()
        self.assertEqual(data['kpis']['manual_approvals']['value'], before + 1)
        latest = data['recent_activity'][0]
        self.assertTrue(latest['title'].startswith('Fee exemption'))
        self.assertEqual(latest['kind'], 'warning')

    def test_approved_scholarship_counted_and_distributed(self):
        before = self._dashboard().get_dashboard_data()
        year = self.env['op.academic.year'].create({
            'name': 'Fee Dash AY', 'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=300)})
        scholarship = self.env['bxi.student.scholarship'].create({
            'student_id': self._student('FDASH-2').id, 'scholarship_type': 'merit', 'academic_year_id': year.id,
            'coverage_type': 'fixed_amount', 'fixed_amount': 500.0,
            'valid_until': fields.Date.today() + timedelta(days=200)})
        scholarship.write({'approval_status': 'approved'})
        after = self._dashboard().get_dashboard_data()
        self.assertEqual(after['kpis']['scholarships']['value'], before['kpis']['scholarships']['value'] + 1)
        distribution = dict(zip(after['charts']['scholarship_distribution']['labels'],
                                after['charts']['scholarship_distribution']['values']))
        label = dict(scholarship._fields['scholarship_type'].selection)['merit']
        previous = dict(zip(before['charts']['scholarship_distribution']['labels'],
                            before['charts']['scholarship_distribution']['values'])).get(label, 0)
        self.assertEqual(distribution[label], previous + 1)
