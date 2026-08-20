from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .scholarship_program import SCHOLARSHIP_TYPES


class StudentScholarship(models.Model):
    _name = 'bxi.student.scholarship'
    _description = 'Student Scholarship'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'valid_from desc'

    name = fields.Char(string='Reference Code', copy=False, readonly=True, default=lambda self: _('New'))
    active = fields.Boolean(default=True)

    student_id = fields.Many2one('op.student', string='Student', required=True, tracking=True)
    class_id = fields.Many2one(
        'op.course', string='Class', compute='_compute_class_section',
        store=True, index=True)
    section_id = fields.Many2one(
        'op.batch', string='Section', compute='_compute_class_section',
        store=True, index=True)

    program_id = fields.Many2one('bxi.scholarship.program', string='Scholarship Name')
    scholarship_type = fields.Selection(SCHOLARSHIP_TYPES, required=True, default='merit', tracking=True)
    academic_year_id = fields.Many2one('op.academic.year', string='Academic Year', required=True)
    reason = fields.Text(string='Reason for Scholarship')

    coverage_type = fields.Selection([
        ('percentage', 'Percentage Discount'),
        ('fixed_amount', 'Fixed Amount'),
    ], required=True, default='percentage')
    coverage_percentage = fields.Float('Coverage Percentage')
    fixed_amount = fields.Monetary('Fixed Amount')
    max_amount_limit = fields.Monetary('Maximum Amount Limit')
    fee_category_scope = fields.Selection([
        ('all', 'All Fee Categories'),
        ('specific', 'Specific Categories'),
    ], string='Applicable Fee Categories', default='all', required=True)
    applicable_fee_category_ids = fields.Many2many(
        'product.product', string='Specific Fee Categories',
        help='Only used when Applicable Fee Categories is set to Specific Categories.')
    priority_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], default='medium')

    fee_line_ids = fields.One2many('bxi.student.scholarship.fee.line', 'scholarship_id', string='Fee Breakdown')
    total_fee_amount = fields.Monetary(compute='_compute_fee_totals', store=True)
    scholarship_amount = fields.Monetary(compute='_compute_fee_totals', store=True)
    net_payable_amount = fields.Monetary(
        string='Balance', compute='_compute_fee_totals', store=True,
        help='Total Fee Amount minus Scholarship Amount, as a snapshot. Not a live read of paid/unpaid invoices.')

    valid_from = fields.Date(required=True, default=fields.Date.context_today)
    valid_until = fields.Date(required=True)
    auto_renew = fields.Boolean(string='Auto-renew for next academic year if student maintains eligibility')

    approval_status = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', required=True, tracking=True)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approval_date = fields.Date(readonly=True, copy=False)
    next_review_date = fields.Date()

    income_certificate_submitted = fields.Boolean()
    academic_marksheet_submitted = fields.Boolean()
    recommendation_letter_submitted = fields.Boolean()
    application_form_submitted = fields.Boolean()
    document_ids = fields.Many2many(
        comodel_name='ir.attachment',
        relation='bxi_scholarship_document_rel',
        column1='scholarship_id', column2='attachment_id',
        string='Supporting Documents')

    notify_student = fields.Boolean(string='Notify student about scholarship changes')
    notify_parent = fields.Boolean(string='Notify parent/guardian')
    notify_monthly_report = fields.Boolean(string='Send monthly scholarship utilization report')

    internal_notes = fields.Text()
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    @api.depends('student_id', 'student_id.course_detail_ids.state')
    def _compute_class_section(self):
        for scholarship in self:
            enrollment = scholarship.student_id.course_detail_ids.filtered(
                lambda line: line.state == 'running')[:1]
            scholarship.class_id = enrollment.course_id
            scholarship.section_id = enrollment.batch_id

    @api.depends('fee_line_ids.total_amount', 'fee_line_ids.discount_amount', 'max_amount_limit')
    def _compute_fee_totals(self):
        for scholarship in self:
            total = sum(scholarship.fee_line_ids.mapped('total_amount'))
            discount = sum(scholarship.fee_line_ids.mapped('discount_amount'))
            if scholarship.max_amount_limit:
                discount = min(discount, scholarship.max_amount_limit)
            scholarship.total_fee_amount = total
            scholarship.scholarship_amount = discount
            scholarship.net_payable_amount = total - discount

    @api.onchange('program_id')
    def _onchange_program_id(self):
        if self.program_id:
            self.scholarship_type = self.program_id.scholarship_type
            self.coverage_type = self.program_id.default_coverage_type
            self.coverage_percentage = self.program_id.default_coverage_percentage
            self.fixed_amount = self.program_id.default_fixed_amount
            self.max_amount_limit = self.program_id.default_max_amount_limit

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.student.scholarship') or _('New')
        return super().create(vals_list)

    def action_submit(self):
        self.write({'approval_status': 'pending'})

    def action_approve(self):
        self.write({
            'approval_status': 'approved',
            'approved_by': self.env.user.id,
            'approval_date': fields.Date.context_today(self),
        })

    def action_reject(self):
        self.write({'approval_status': 'rejected'})

    def action_reset_to_draft(self):
        self.write({'approval_status': 'draft', 'approved_by': False, 'approval_date': False})

    def action_print_report(self):
        self.ensure_one()
        return self.env.ref('bxi_school_scholarship.action_report_scholarship').report_action(self)


class StudentScholarshipFeeLine(models.Model):
    _name = 'bxi.student.scholarship.fee.line'
    _description = 'Student Scholarship Fee Line'

    scholarship_id = fields.Many2one('bxi.student.scholarship', required=True, ondelete='cascade')
    fee_category_id = fields.Many2one('product.product', string='Fee Category', required=True)
    total_amount = fields.Monetary(required=True)
    # The overall scholarship_amount cap (max_amount_limit) is applied once,
    # at the header level, not distributed back across lines - so a capped
    # line-level discount_amount here can sum to more than the capped
    # header scholarship_amount. That's expected: these lines show the
    # theoretical per-category discount before the header-level cap.
    discount_amount = fields.Monetary(compute='_compute_discount_amount', store=True)
    net_amount = fields.Monetary(compute='_compute_discount_amount', store=True)
    currency_id = fields.Many2one(related='scholarship_id.currency_id')

    @api.depends(
        'total_amount', 'fee_category_id',
        'scholarship_id.coverage_type', 'scholarship_id.coverage_percentage',
        'scholarship_id.fixed_amount', 'scholarship_id.fee_category_scope',
        'scholarship_id.applicable_fee_category_ids', 'scholarship_id.fee_line_ids.fee_category_id')
    def _compute_discount_amount(self):
        for line in self:
            scholarship = line.scholarship_id
            in_scope = scholarship.fee_category_scope == 'all' \
                or line.fee_category_id in scholarship.applicable_fee_category_ids
            if not in_scope:
                discount = 0.0
            elif scholarship.coverage_type == 'percentage':
                discount = line.total_amount * scholarship.coverage_percentage / 100.0
            else:
                in_scope_siblings = scholarship.fee_line_ids.filtered(
                    lambda l: scholarship.fee_category_scope == 'all'
                    or l.fee_category_id in scholarship.applicable_fee_category_ids)
                discount = scholarship.fixed_amount / len(in_scope_siblings) if in_scope_siblings else 0.0
            line.discount_amount = discount
            line.net_amount = line.total_amount - discount

    @api.constrains('scholarship_id', 'fee_category_id')
    def _check_unique_fee_category(self):
        for line in self:
            duplicates = line.scholarship_id.fee_line_ids.filtered(
                lambda l: l.fee_category_id == line.fee_category_id and l.id != line.id)
            if duplicates:
                raise ValidationError(_(
                    '%(category)s is already listed on this scholarship.',
                    category=line.fee_category_id.display_name))
