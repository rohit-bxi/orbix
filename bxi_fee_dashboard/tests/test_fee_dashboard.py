# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
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
