from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

EXEMPTION_TYPES = [
    ('financial_hardship', 'Financial Hardship'),
    ('merit_based', 'Merit-Based'),
    ('sibling_discount', 'Sibling Discount'),
    ('sports_achievement', 'Sports Achievement'),
    ('staff_dependent', 'Staff Dependent'),
    ('special_circumstances', 'Special Circumstances'),
    ('other', 'Other'),
]

REJECTION_REASON_CATEGORIES = [
    ('incomplete_documents', 'Incomplete Documents'),
    ('not_eligible', 'Does Not Meet Eligibility Criteria'),
    ('income_exceeds_limit', 'Family Income Exceeds Limit'),
    ('duplicate_request', 'Duplicate Request'),
    ('policy_violation', 'Policy Violation'),
    ('other', 'Other'),
]


class FeeExemptionRequest(models.Model):
    _name = 'bxi.fee.exemption.request'
    _description = 'Fee Exemption Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'submitted_date desc'

    name = fields.Char(string='Request ID', copy=False, readonly=True, default=lambda self: _('New'))
    active = fields.Boolean(default=True)

    # Student Information
    student_id = fields.Many2one('op.student', string='Student', required=True, tracking=True)
    class_id = fields.Many2one(
        'op.course', string='Class', compute='_compute_class_section',
        store=True, index=True)
    section_id = fields.Many2one(
        'op.batch', string='Section', compute='_compute_class_section',
        store=True, index=True)
    roll_number = fields.Char(compute='_compute_class_section', store=True)
    admission_number = fields.Char(related='student_id.gr_no', string='Admission Number')
    date_of_birth = fields.Date(related='student_id.birth_date')

    # Parent/Guardian Information
    parent_id = fields.Many2one('op.parent', string='Parent/Guardian')
    parent_ids = fields.Many2many('op.parent', related='student_id.parent_ids', string='Student Parents')

    # Exemption Request Details
    exemption_type = fields.Selection(EXEMPTION_TYPES, required=True, tracking=True)
    request_value_type = fields.Selection([
        ('amount', 'Fixed Amount'),
        ('percentage', 'Percentage'),
    ], required=True, default='amount', tracking=True)
    requested_amount = fields.Monetary(string='Requested Amount', tracking=True)
    requested_percentage = fields.Float(string='Requested Percentage')
    reason = fields.Text(string='Reason for Request', required=True)
    additional_notes = fields.Text()

    # Eligibility snapshot (as declared/observed at submission time)
    academic_performance = fields.Float(string='Academic Performance (%)')
    attendance_percentage = fields.Float(string='Attendance (%)')
    family_income = fields.Monetary(string='Family Income (per annum)')
    sibling_count = fields.Integer(string='Number of Siblings in School')
    previous_exemptions = fields.Char(string='Previous Exemptions')

    # Payment Information - live, read-only, never written back to invoicing
    total_fee_amount = fields.Monetary(compute='_compute_payment_summary')
    total_paid_amount = fields.Monetary(compute='_compute_payment_summary')
    pending_amount = fields.Monetary(compute='_compute_payment_summary')

    # Approval & Processing
    submitted_date = fields.Date(required=True, default=fields.Date.context_today)
    status = fields.Selection([
        ('draft', 'Draft'),
        ('pending_review', 'Pending Review'),
        ('under_review', 'Under Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', required=True, tracking=True)
    exemption_id = fields.Many2one('bxi.fee.exemption', string='Granted Exemption', readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approval_date = fields.Date(readonly=True, copy=False)

    # Rejection Details (set by the Reject wizard)
    rejection_reason_category = fields.Selection(REJECTION_REASON_CATEGORIES, readonly=True, copy=False)
    rejection_reason = fields.Text(string='Rejection Reason (sent to parent)', readonly=True, copy=False)
    reapplication_suggestions = fields.Text(readonly=True, copy=False)
    rejected_by = fields.Many2one('res.users', readonly=True, copy=False)
    rejection_date = fields.Date(readonly=True, copy=False)
    allow_reapplication_after_days = fields.Integer(readonly=True, copy=False)
    internal_notes = fields.Text()

    # Supporting Documents
    document_ids = fields.Many2many(
        comodel_name='ir.attachment',
        relation='bxi_exemption_request_document_rel',
        column1='exemption_request_id', column2='attachment_id',
        string='Supporting Documents')

    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    @api.depends('student_id', 'student_id.course_detail_ids.state')
    def _compute_class_section(self):
        for request in self:
            enrollment = request.student_id.course_detail_ids.filtered(
                lambda line: line.state == 'running')[:1]
            request.class_id = enrollment.course_id
            request.section_id = enrollment.batch_id
            request.roll_number = enrollment.roll_number

    @api.depends('student_id')
    def _compute_payment_summary(self):
        for request in self:
            summary = request.student_id.get_fee_payment_summary() if request.student_id else {}
            request.total_fee_amount = summary.get('total_fee_amount', 0.0)
            request.total_paid_amount = summary.get('total_paid_amount', 0.0)
            request.pending_amount = summary.get('pending_amount', 0.0)

    @api.onchange('student_id')
    def _onchange_student_id(self):
        if self.student_id:
            self.parent_id = self.student_id.parent_ids[:1]

    @api.constrains('requested_amount', 'requested_percentage', 'request_value_type')
    def _check_requested_value(self):
        for request in self:
            if request.request_value_type == 'amount' and request.requested_amount <= 0:
                raise ValidationError(_('Requested Amount must be greater than zero.'))
            if request.request_value_type == 'percentage' and not (0 < request.requested_percentage <= 100):
                raise ValidationError(_('Requested Percentage must be between 0 and 100.'))

    def _check_status(self, allowed, action_label):
        for request in self:
            if request.status not in allowed:
                raise UserError(_(
                    'Cannot %(action)s: request %(name)s is in status "%(status)s".',
                    action=action_label, name=request.name, status=request.status))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.fee.exemption.request') or _('New')
        return super().create(vals_list)

    def action_submit(self):
        self._check_status(('draft',), _('submit for review'))
        self.write({'status': 'pending_review'})

    def action_start_review(self):
        self._check_status(('pending_review',), _('start review'))
        self.write({'status': 'under_review'})

    def action_open_approve_wizard(self):
        self.ensure_one()
        self._check_status(('pending_review', 'under_review'), _('approve'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Approve Exemption Request'),
            'res_model': 'bxi.fee.exemption.approve.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def action_open_reject_wizard(self):
        self.ensure_one()
        self._check_status(('pending_review', 'under_review'), _('reject'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject Exemption Request'),
            'res_model': 'bxi.fee.exemption.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def action_view_exemption(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Fee Exemption'),
            'res_model': 'bxi.fee.exemption',
            'view_mode': 'form',
            'res_id': self.exemption_id.id,
        }

    def action_reset_to_draft(self):
        self._check_status(('rejected',), _('reset to draft'))
        self.write({
            'status': 'draft',
            'rejection_reason_category': False, 'rejection_reason': False,
            'reapplication_suggestions': False, 'rejected_by': False,
            'rejection_date': False, 'allow_reapplication_after_days': 0,
        })
