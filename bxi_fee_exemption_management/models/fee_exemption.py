from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .fee_exemption_request import EXEMPTION_TYPES


class FeeExemption(models.Model):
    _name = 'bxi.fee.exemption'
    _description = 'Fee Exemption'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'valid_from desc'

    name = fields.Char(string='Exemption ID', copy=False, readonly=True, default=lambda self: _('New'))
    active = fields.Boolean(default=True)

    request_id = fields.Many2one(
        'bxi.fee.exemption.request', string='Source Request', readonly=True, copy=False,
        help='The parent-submitted request this exemption was granted from, if any. '
             'Empty when a staff member created this exemption directly.')

    # Student Information
    student_id = fields.Many2one('op.student', string='Student', required=True, tracking=True)
    class_id = fields.Many2one(
        'op.course', string='Class', compute='_compute_class_section',
        store=True, index=True)
    section_id = fields.Many2one(
        'op.batch', string='Section', compute='_compute_class_section',
        store=True, index=True)
    roll_number = fields.Char(compute='_compute_class_section', store=True)
    parent_id = fields.Many2one('op.parent', string='Parent/Guardian')
    parent_ids = fields.Many2many('op.parent', related='student_id.parent_ids', string='Student Parents')

    # Exemption Information
    exemption_type = fields.Selection(EXEMPTION_TYPES, required=True, default='financial_hardship', tracking=True)
    category = fields.Selection([
        ('full_exemption', 'Full Exemption'),
        ('partial_exemption', 'Partial Exemption'),
    ], required=True, default='partial_exemption')
    exemption_method = fields.Selection([
        ('percentage', 'Percentage'),
        ('fixed_amount', 'Fixed Amount'),
    ], required=True, default='fixed_amount')
    coverage_percentage = fields.Float('Coverage Percentage')
    fixed_amount = fields.Monetary('Fixed Amount')
    max_exemption_amount = fields.Monetary('Maximum Exemption Amount')
    fee_category_scope = fields.Selection([
        ('all', 'All Fee Categories'),
        ('specific', 'Specific Categories'),
    ], string='Applicable Fee Categories', default='all', required=True)
    applicable_fee_category_ids = fields.Many2many(
        'product.product', string='Specific Fee Categories',
        help='Only used when Applicable Fee Categories is set to Specific Categories.')
    priority_level = fields.Selection([
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
    ], default='normal')
    reason = fields.Text(string='Reason for Exemption')

    fee_line_ids = fields.One2many('bxi.fee.exemption.fee.line', 'exemption_id', string='Fee Category Breakdown')
    total_fee_amount = fields.Monetary(compute='_compute_fee_totals', store=True)
    exemption_amount = fields.Monetary(compute='_compute_fee_totals', store=True)
    net_payable_amount = fields.Monetary(
        string='Net Payable', compute='_compute_fee_totals', store=True,
        help='Total Fee Amount minus Exemption Amount, as a snapshot. Not a live read of paid/unpaid invoices.')

    # Validity Period
    valid_from = fields.Date(required=True, default=fields.Date.context_today)
    valid_until = fields.Date(required=True)
    auto_renew = fields.Boolean(string='Auto-renew for next academic year if student maintains eligibility')

    # Eligibility Criteria
    min_academic_percentage = fields.Float(string='Minimum Academic Percentage')
    min_attendance_percentage = fields.Float(string='Minimum Attendance (%)')
    family_income_limit = fields.Monetary(string='Family Income Limit (per year)')
    sibling_count_required = fields.Integer(string='Number of Siblings in School')
    additional_conditions = fields.Text()

    # Approval Settings
    approval_status = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', required=True, tracking=True)
    approved_by = fields.Many2one('res.users', copy=False)
    approval_date = fields.Date(copy=False)
    next_review_date = fields.Date()
    approval_notes = fields.Text()

    # Supporting Documents
    document_ids = fields.Many2many(
        comodel_name='ir.attachment',
        relation='bxi_exemption_document_rel',
        column1='exemption_id', column2='attachment_id',
        string='Supporting Documents')

    # Notification Settings
    notify_parent = fields.Boolean(string='Notify parent/guardian about changes')
    notify_sms = fields.Boolean(string='Send SMS notification')
    notify_email = fields.Boolean(string='Send email notification')

    internal_notes = fields.Text()
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    @api.depends('student_id', 'student_id.course_detail_ids.state')
    def _compute_class_section(self):
        for exemption in self:
            enrollment = exemption.student_id.course_detail_ids.filtered(
                lambda line: line.state == 'running')[:1]
            exemption.class_id = enrollment.course_id
            exemption.section_id = enrollment.batch_id
            exemption.roll_number = enrollment.roll_number

    @api.depends('fee_line_ids.total_amount', 'fee_line_ids.exemption_applied', 'max_exemption_amount')
    def _compute_fee_totals(self):
        for exemption in self:
            total = sum(exemption.fee_line_ids.mapped('total_amount'))
            applied = sum(exemption.fee_line_ids.mapped('exemption_applied'))
            if exemption.max_exemption_amount:
                applied = min(applied, exemption.max_exemption_amount)
            exemption.total_fee_amount = total
            exemption.exemption_amount = applied
            exemption.net_payable_amount = total - applied

    @api.constrains('exemption_method', 'coverage_percentage', 'fixed_amount', 'max_exemption_amount')
    def _check_exemption_values(self):
        for exemption in self:
            if exemption.exemption_method == 'percentage' and not (0 <= exemption.coverage_percentage <= 100):
                raise ValidationError(_('Coverage Percentage must be between 0 and 100.'))
            if exemption.exemption_method == 'fixed_amount' and exemption.fixed_amount < 0:
                raise ValidationError(_('Fixed Amount cannot be negative.'))
            if exemption.max_exemption_amount < 0:
                raise ValidationError(_('Maximum Exemption Amount cannot be negative.'))

    @api.constrains('valid_from', 'valid_until')
    def _check_validity_period(self):
        for exemption in self:
            if exemption.valid_from and exemption.valid_until and exemption.valid_from > exemption.valid_until:
                raise ValidationError(_('Valid Until must be on or after Valid From.'))

    @api.onchange('student_id')
    def _onchange_student_id(self):
        if self.student_id:
            self.parent_id = self.student_id.parent_ids[:1]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.fee.exemption') or _('New')
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

    def action_open_delete_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Delete Fee Exemption'),
            'res_model': 'bxi.fee.exemption.delete.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_exemption_id': self.id},
        }


class FeeExemptionLine(models.Model):
    _name = 'bxi.fee.exemption.fee.line'
    _description = 'Fee Exemption Fee Line'

    exemption_id = fields.Many2one('bxi.fee.exemption', required=True, ondelete='cascade')
    fee_category_id = fields.Many2one('product.product', string='Fee Category', required=True)
    total_amount = fields.Monetary(required=True)
    # The overall exemption_amount cap (max_exemption_amount) is applied once,
    # at the header level, not distributed back across lines - so a capped
    # line-level exemption_applied here can sum to more than the capped
    # header exemption_amount. That's expected: these lines show the
    # theoretical per-category exemption before the header-level cap.
    exemption_applied = fields.Monetary(compute='_compute_exemption_applied', store=True)
    net_amount = fields.Monetary(compute='_compute_exemption_applied', store=True)
    currency_id = fields.Many2one(related='exemption_id.currency_id')

    @api.depends(
        'total_amount', 'fee_category_id',
        'exemption_id.exemption_method', 'exemption_id.coverage_percentage',
        'exemption_id.fixed_amount', 'exemption_id.fee_category_scope',
        'exemption_id.applicable_fee_category_ids', 'exemption_id.fee_line_ids.fee_category_id')
    def _compute_exemption_applied(self):
        for line in self:
            exemption = line.exemption_id
            in_scope = exemption.fee_category_scope == 'all' \
                or line.fee_category_id in exemption.applicable_fee_category_ids
            if not in_scope:
                applied = 0.0
            elif exemption.exemption_method == 'percentage':
                applied = line.total_amount * exemption.coverage_percentage / 100.0
            else:
                in_scope_siblings = exemption.fee_line_ids.filtered(
                    lambda l: exemption.fee_category_scope == 'all'
                    or l.fee_category_id in exemption.applicable_fee_category_ids)
                applied = exemption.fixed_amount / len(in_scope_siblings) if in_scope_siblings else 0.0
            # A fee line's exemption can never exceed what's actually owed on that
            # line - clamp here so net_amount (and net_payable_amount) can't go
            # negative regardless of how coverage_percentage/fixed_amount is set.
            applied = max(0.0, min(applied, line.total_amount))
            line.exemption_applied = applied
            line.net_amount = line.total_amount - applied

    @api.constrains('exemption_id', 'fee_category_id')
    def _check_unique_fee_category(self):
        for line in self:
            duplicates = line.exemption_id.fee_line_ids.filtered(
                lambda l: l.fee_category_id == line.fee_category_id and l.id != line.id)
            if duplicates:
                raise ValidationError(_(
                    '%(category)s is already listed on this exemption.',
                    category=line.fee_category_id.display_name))
