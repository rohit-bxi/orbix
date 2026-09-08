# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from freezegun import freeze_time

from odoo.tests.common import tagged

from .common import TestRteAdmissionCommon


@tagged('post_install', '-at_install')
class TestResConfigSettings(TestRteAdmissionCommon):

    def _set_param(self, key, value):
        self.env['ir.config_parameter'].sudo().set_param(key, value)

    def test_default_quota_percentage_is_25_when_unset(self):
        course = self.env['op.course'].create({
            'name': 'Config Course A', 'code': 'CFGA01', 'total_intake': 40,
        })
        self.assertEqual(course.rte_seats, 10)

    def test_configured_quota_percentage_changes_new_seat_computation(self):
        self._set_param('bxi_rte_admission.quota_percentage', '10.0')
        course = self.env['op.course'].create({
            'name': 'Config Course B', 'code': 'CFGB01', 'total_intake': 40,
        })
        self.assertEqual(course.rte_seats, 4)

    def test_configured_quota_percentage_applies_on_recompute(self):
        course = self.env['op.course'].create({
            'name': 'Config Course C', 'code': 'CFGC01', 'total_intake': 40,
        })
        self.assertEqual(course.rte_seats, 10)
        self._set_param('bxi_rte_admission.quota_percentage', '50.0')
        # Touch a dependency to force a recompute of the existing record.
        course.total_intake = 40
        self.assertEqual(course.rte_seats, 20)

    def test_manual_override_ignores_configured_percentage(self):
        self._set_param('bxi_rte_admission.quota_percentage', '50.0')
        course = self.env['op.course'].create({
            'name': 'Config Course D', 'code': 'CFGD01', 'total_intake': 40,
            'rte_seats_manual': 3,
        })
        self.assertEqual(course.rte_seats, 3)

    def test_confirmation_reminder_uses_configured_lead_time(self):
        self._set_param('bxi_rte_admission.confirmation_reminder_days', '1')
        with freeze_time('2026-01-01'):
            admission = self._make_admission(rte_state='allotted')
            admission.confirmation_deadline = '2026-01-02'
            admission._cron_confirmation_deadline_reminder()
        messages = admission.message_ids.mapped('body')
        self.assertTrue(any('confirmation deadline' in (m or '') for m in messages))

    def test_confirmation_reminder_respects_shorter_configured_lead_time(self):
        self._set_param('bxi_rte_admission.confirmation_reminder_days', '1')
        with freeze_time('2026-01-01'):
            admission = self._make_admission(rte_state='allotted')
            # 5 days out, but the configured lead time is only 1 day.
            admission.confirmation_deadline = '2026-01-06'
            admission._cron_confirmation_deadline_reminder()
        messages = admission.message_ids.mapped('body')
        self.assertFalse(any('confirmation deadline' in (m or '') for m in messages))
