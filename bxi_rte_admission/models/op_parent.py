# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Disha-Nirdesh 2026-27, para 2.2: "weaker section" (2.2.1) is a single
# income-based category; "disadvantaged group" (2.2.2) is a fixed list of
# 8 sub-categories. Categories whose income cap applies also carry it in
# RTE_INCOME_CAPPED below.
RTE_CATEGORIES = [
    ('weaker_section', 'Weaker Section (Income ≤ ₹2.5L)'),
    ('sc', 'Scheduled Caste'),
    ('st', 'Scheduled Tribe'),
    ('orphan', 'Orphan'),
    ('hiv_cancer', 'HIV/Cancer Affected (Child or Parent/Guardian)'),
    ('war_widow', 'Child of a War Widow'),
    ('disabled', 'Child with Benchmark Disability'),
    ('obc_sbc_income', 'OBC/SBC (Income ≤ ₹2.5L)'),
    ('bpl', 'BPL List (Central or State)'),
]

RTE_INCOME_CAPPED = ('weaker_section', 'obc_sbc_income')
RTE_INCOME_CAP = 250000.0

RTE_BPL_LIST_TYPES = [
    ('central', 'Central List'),
    ('state', 'State List'),
]


class OpParent(models.Model):
    _inherit = 'op.parent'

    rte_income_certificate = fields.Binary(
        string='Income Certificate', attachment=True)
    rte_income_certificate_filename = fields.Char(
        string='Income Certificate Filename')
    rte_income_certificate_financial_year = fields.Char(
        string='Income Certificate Financial Year',
        help='Financial year (e.g. 2025-26) the income certificate was '
             'issued for. Must be renewed every academic session (para '
             '7.3/7.7).')
    rte_annual_income = fields.Monetary(
        string='Annual Income', currency_field='currency_id',
        help='Annual family income as per the income certificate. '
             'Required, and capped at ₹2.5 lakh, for the Weaker '
             'Section and OBC/SBC categories (para 2.2.1/2.2.2(g)).')
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)
    rte_category = fields.Selection(
        RTE_CATEGORIES, string='RTE Category')
    rte_category_certificate = fields.Binary(
        string='Category Certificate', attachment=True)
    rte_category_certificate_filename = fields.Char(
        string='Category Certificate Filename')
    rte_bpl_number = fields.Char(string='BPL Card Number')
    rte_bpl_list_type = fields.Selection(
        RTE_BPL_LIST_TYPES, string='BPL List')

    @api.constrains('rte_category', 'rte_annual_income')
    def _check_rte_income_cap(self):
        for parent in self:
            if parent.rte_category not in RTE_INCOME_CAPPED:
                continue
            if not parent.rte_annual_income:
                raise ValidationError(_(
                    'Annual Income is required for the %s category.')
                    % dict(RTE_CATEGORIES)[parent.rte_category])
            if parent.rte_annual_income > RTE_INCOME_CAP:
                raise ValidationError(_(
                    'Annual Income for the %s category cannot exceed '
                    '₹2.5 lakh.') % dict(RTE_CATEGORIES)[parent.rte_category])

    @api.constrains('rte_category', 'rte_bpl_number', 'rte_bpl_list_type')
    def _check_rte_bpl_fields(self):
        for parent in self:
            if parent.rte_category == 'bpl' and not (
                    parent.rte_bpl_number and parent.rte_bpl_list_type):
                raise ValidationError(_(
                    'BPL Card Number and BPL List are required for the '
                    'BPL category.'))

    @api.constrains('rte_income_certificate_financial_year')
    def _check_rte_income_certificate_financial_year(self):
        """Para 7.7: the income certificate must be issued for a specific
        financial year (e.g. 2025-26 for the 2026-27 admission session).
        Only enforced when the required year is configured, so this stays
        advisory until an admin sets it for the current session."""
        required_fy = self.env['ir.config_parameter'].sudo().get_param(
            'bxi_rte_admission.income_certificate_financial_year')
        if not required_fy:
            return
        for parent in self:
            fy = parent.rte_income_certificate_financial_year
            if fy and fy != required_fy:
                raise ValidationError(_(
                    'The income certificate must be for financial year %s '
                    '(para 7.7). Given: %s.') % (required_fy, fy))
