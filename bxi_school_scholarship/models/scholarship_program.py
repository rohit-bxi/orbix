from odoo import fields, models

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
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
