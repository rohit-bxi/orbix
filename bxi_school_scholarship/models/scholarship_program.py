# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import api, fields, models

SCHOLARSHIP_TYPES = [
    ('merit', 'Merit-Based'),
    ('need_based', 'Need-Based'),
    ('sports', 'Sports Scholarship'),
    ('academic_excellence', 'Academic Excellence'),
    ('other', 'Other'),
]


class ScholarshipProgram(models.Model):
    _name = 'bxi.scholarship.program'
    _description = 'Scholarship Program'
    _order = 'name'

    name = fields.Char(required=True)
    scholarship_type = fields.Selection(SCHOLARSHIP_TYPES, required=True, default='merit')
    description = fields.Text()
    default_coverage_type = fields.Selection([
        ('percentage', 'Percentage Discount'),
        ('fixed_amount', 'Fixed Amount'),
    ], string='Default Coverage Type', default='percentage')
    default_coverage_percentage = fields.Float('Default Coverage (%)')
    default_fixed_amount = fields.Monetary('Default Fixed Amount')
    default_max_amount_limit = fields.Monetary('Default Maximum Amount Limit')
    budget_amount = fields.Monetary(
        'Budget Allocated', help='Total budget allocated to this scholarship program.')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    scholarship_ids = fields.One2many('bxi.student.scholarship', 'program_id', string='Scholarships')
    recipient_count = fields.Integer(compute='_compute_budget_usage')
    amount_disbursed = fields.Monetary(compute='_compute_budget_usage')
    budget_utilization = fields.Float('Budget Utilization (%)', compute='_compute_budget_usage')

    @api.depends('scholarship_ids.scholarship_amount', 'scholarship_ids.approval_status',
                 'scholarship_ids.active', 'budget_amount')
    def _compute_budget_usage(self):
        for program in self:
            approved = program.scholarship_ids.filtered(
                lambda s: s.approval_status == 'approved' and s.active)
            program.recipient_count = len(approved)
            program.amount_disbursed = sum(approved.mapped('scholarship_amount'))
            program.budget_utilization = (
                program.amount_disbursed / program.budget_amount * 100.0) if program.budget_amount else 0.0
