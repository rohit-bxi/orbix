# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rte_quota_percentage = fields.Float(
        string='RTE Quota Percentage', default=25.0,
        config_parameter='bxi_rte_admission.quota_percentage',
        help='Percentage of a course\'s Total Intake reserved for RTE '
             'Section 12(1)(c) admissions. Applied to every RTE-active '
             'course unless a per-course manual override is set.')
    rte_confirmation_reminder_days = fields.Integer(
        string='Confirmation Reminder Lead Time (days)', default=3,
        config_parameter='bxi_rte_admission.confirmation_reminder_days',
        help='How many days before an Allotted applicant\'s confirmation '
             'deadline the daily reminder cron posts a chatter notice.')
    rte_income_certificate_financial_year = fields.Char(
        string='Required Income Certificate Financial Year',
        config_parameter='bxi_rte_admission.income_certificate_financial_year',
        help='Financial year (e.g. 2025-26) the income certificate must be '
             'issued for this admission session (para 7.7). Leave blank to '
             'skip the check. Update this every session.')
