from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class StudentRefundRequest(models.Model):
    _name = 'bxi.student.refund.request'
    _description = 'Student Fee Refund Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'request_date desc'

    name = fields.Char(string='Refund ID', copy=False, readonly=True, default=lambda self: _('New'))
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

    # Refund Request Details
    refund_type = fields.Selection([
        ('fee_overpayment', 'Fee Overpayment'),
        ('withdrawal', 'Withdrawal Refund'),
        ('transport_fee', 'Transport Fee Refund'),
        ('exam_fee', 'Exam Fee Refund'),
        ('activity_fee', 'Activity Fee Refund'),
        ('lab_fee', 'Lab Fee Refund'),
        ('special_circumstances', 'Special Circumstances'),
        ('other', 'Other'),
    ], required=True, tracking=True)
    refund_amount = fields.Monetary(required=True, tracking=True)
    original_payment_mode = fields.Selection([
        ('upi', 'UPI'),
        ('bank_transfer', 'Bank Transfer'),
        ('cash', 'Cash'),
        ('cheque', 'Cheque'),
        ('card', 'Card'),
        ('online', 'Online'),
    ], string='Original Payment Mode')
    transaction_reference = fields.Char(string='Transaction Reference Number')
    duplicate_transaction_reference = fields.Char(string='Duplicate Transaction ID')
    reason = fields.Text(string='Reason for Refund', required=True)
    additional_notes = fields.Text()

    # Payment Information - live, read-only, never written back to invoicing
    total_fee_amount = fields.Monetary(compute='_compute_payment_summary')
    total_paid_amount = fields.Monetary(compute='_compute_payment_summary')
    excess_amount = fields.Monetary(compute='_compute_payment_summary')
    pending_amount = fields.Monetary(compute='_compute_payment_summary')

    # Refund Method Details
    preferred_refund_mode = fields.Selection([
        ('bank_transfer', 'Bank Transfer (NEFT/RTGS)'),
        ('upi', 'UPI'),
        ('cash', 'Cash'),
        ('cheque', 'Cheque'),
    ])
    account_holder_name = fields.Char()
    bank_account_number = fields.Char()
    ifsc_code = fields.Char(string='IFSC Code')
    bank_name = fields.Char()
    branch_name = fields.Char()

    # Approval & Processing
    request_date = fields.Date(required=True, default=fields.Date.context_today)
    priority = fields.Selection([
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
    ], default='normal')
    status = fields.Selection([
        ('draft', 'Draft'),
        ('pending_review', 'Pending Review'),
        ('under_review', 'Under Review'),
        ('approved', 'Approved'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),
    ], default='draft', required=True, tracking=True)
    assigned_to = fields.Many2one('res.users', string='Assigned To')
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approval_date = fields.Date(readonly=True, copy=False)
    processed_date = fields.Date(readonly=True, copy=False)
    processing_notes = fields.Text()
    days_pending = fields.Integer(compute='_compute_days_pending')

    # Payment Tracking (manual entry after paying outside Odoo)
    refund_utr = fields.Char(string='UTR/Transaction ID')
    refund_completion_date = fields.Date()
    refund_confirmation_notes = fields.Text()

    # Supporting Documents
    original_fee_receipt_submitted = fields.Boolean()
    transfer_certificate_submitted = fields.Boolean(string='Transfer Certificate Submitted')
    bank_account_proof_submitted = fields.Boolean()
    parent_request_letter_submitted = fields.Boolean()
    document_ids = fields.Many2many(
        comodel_name='ir.attachment',
        relation='bxi_refund_document_rel',
        column1='refund_request_id', column2='attachment_id',
        string='Supporting Documents')

    # Notification Settings (flags only, no email/SMS sent in v1)
    notify_parent = fields.Boolean(string='Notify parent/guardian about refund request')
    notify_sms = fields.Boolean(string='Send SMS notification')
    notify_email = fields.Boolean(string='Send email notification')
    notify_auto_update = fields.Boolean(string='Auto-update on status change')

    internal_notes = fields.Text()
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    @api.depends('student_id', 'student_id.course_detail_ids.state')
    def _compute_class_section(self):
        for refund in self:
            enrollment = refund.student_id.course_detail_ids.filtered(
                lambda line: line.state == 'running')[:1]
            refund.class_id = enrollment.course_id
            refund.section_id = enrollment.batch_id
            refund.roll_number = enrollment.roll_number

    @api.depends('student_id')
    def _compute_payment_summary(self):
        for refund in self:
            summary = refund.student_id.get_fee_payment_summary() if refund.student_id else {}
            refund.total_fee_amount = summary.get('total_fee_amount', 0.0)
            refund.total_paid_amount = summary.get('total_paid_amount', 0.0)
            refund.excess_amount = summary.get('excess_amount', 0.0)
            refund.pending_amount = summary.get('pending_amount', 0.0)

    @api.depends('request_date', 'status')
    def _compute_days_pending(self):
        today = fields.Date.context_today(self)
        for refund in self:
            if refund.request_date and refund.status not in ('completed', 'rejected', 'draft'):
                refund.days_pending = (today - refund.request_date).days
            else:
                refund.days_pending = 0

    @api.onchange('student_id')
    def _onchange_student_id(self):
        if self.student_id:
            self.parent_id = self.student_id.parent_ids[:1]

    @api.constrains('refund_amount', 'student_id')
    def _check_refund_amount(self):
        for refund in self:
            if refund.refund_amount <= 0:
                raise ValidationError(_('Refund amount must be greater than zero.'))
            # A refund can never exceed what the student actually paid in, regardless
            # of refund_type - this is the hard ceiling even where excess_amount (which
            # only makes sense for a pure fee-overpayment refund) doesn't apply.
            if refund.refund_amount > refund.total_paid_amount + 0.01:
                raise ValidationError(_(
                    'Refund amount (%(amount)s) cannot exceed the total amount this student has paid (%(paid)s).',
                    amount=refund.refund_amount, paid=refund.total_paid_amount))

    def _check_status(self, allowed, action_label):
        for refund in self:
            if refund.status not in allowed:
                raise UserError(_(
                    'Cannot %(action)s: refund %(name)s is in status "%(status)s".',
                    action=action_label, name=refund.name, status=refund.status))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.student.refund.request') or _('New')
        return super().create(vals_list)

    def action_submit(self):
        self._check_status(('draft',), _('submit for review'))
        self.write({'status': 'pending_review'})

    def action_start_review(self):
        self._check_status(('pending_review',), _('start review'))
        self.write({'status': 'under_review'})

    def action_approve(self):
        self._check_status(('pending_review', 'under_review'), _('approve'))
        self.write({
            'status': 'approved',
            'approved_by': self.env.user.id,
            'approval_date': fields.Date.context_today(self),
        })

    def action_reject(self):
        self._check_status(('pending_review', 'under_review', 'approved'), _('reject'))
        self.write({'status': 'rejected'})

    def action_start_processing(self):
        self._check_status(('approved',), _('start processing'))
        self.write({'status': 'processing'})

    def action_approve_and_process(self):
        self.action_approve()
        self.action_start_processing()

    def action_complete(self):
        self._check_status(('processing',), _('mark completed'))
        for refund in self:
            if not refund.refund_utr:
                raise ValidationError(_('Enter the UTR/Transaction ID before marking this refund completed.'))
            refund.write({
                'status': 'completed',
                'refund_completion_date': fields.Date.context_today(self),
            })

    def action_reset_to_draft(self):
        self.write({
            'status': 'draft', 'approved_by': False, 'approval_date': False,
            'processed_date': False, 'refund_utr': False,
            'refund_completion_date': False, 'refund_confirmation_notes': False,
        })
