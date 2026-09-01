from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FeeExemptionApproveWizard(models.TransientModel):
    _name = 'bxi.fee.exemption.approve.wizard'
    _description = 'Approve Fee Exemption Request'

    request_id = fields.Many2one('bxi.fee.exemption.request', required=True)

    # Read-only context from the request
    student_id = fields.Many2one(related='request_id.student_id', readonly=True)
    parent_id = fields.Many2one(related='request_id.parent_id', readonly=True)
    class_id = fields.Many2one(related='request_id.class_id', readonly=True)
    exemption_type = fields.Selection(related='request_id.exemption_type', readonly=True)
    requested_amount = fields.Monetary(related='request_id.requested_amount', readonly=True)
    reason = fields.Text(related='request_id.reason', readonly=True)
    document_ids = fields.Many2many(related='request_id.document_ids', readonly=True)
    currency_id = fields.Many2one(related='request_id.currency_id', readonly=True)

    # Approval Settings
    approval_type = fields.Selection([
        ('full_approval', 'Full Approval'),
        ('partial_approval', 'Partial Approval'),
    ], required=True, default='full_approval')
    exemption_method = fields.Selection([
        ('percentage', 'Percentage'),
        ('fixed_amount', 'Fixed Amount'),
    ], required=True, default='fixed_amount')
    approved_amount = fields.Monetary(string='Approved Amount', required=True)
    fee_category_scope = fields.Selection([
        ('all', 'All Fee Categories'),
        ('specific', 'Specific Categories'),
    ], string='Exemption Category', default='all', required=True)
    applicable_fee_category_ids = fields.Many2many('product.product', string='Specific Fee Categories')
    priority_level = fields.Selection([
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
    ], default='normal')

    # Validity Period
    valid_from = fields.Date(required=True, default=fields.Date.context_today)
    valid_until = fields.Date(required=True)
    auto_renew = fields.Boolean(string='Auto-renew for next academic year')

    # Approval Details
    approved_by = fields.Many2one('res.users', default=lambda self: self.env.user, required=True)
    approval_date = fields.Date(default=fields.Date.context_today, required=True)
    approval_notes = fields.Text()
    internal_remarks = fields.Text(string='Internal Remarks (Not visible to parent)')

    # Financial Impact Summary
    total_fee_amount = fields.Monetary(compute='_compute_financial_impact')
    current_pending_amount = fields.Monetary(compute='_compute_financial_impact')
    new_pending_amount = fields.Monetary(compute='_compute_financial_impact')

    # Notification Settings
    notify_parent = fields.Boolean(string='Send approval notification to parent via email')
    notify_sms = fields.Boolean(string='Send SMS notification to registered mobile number')
    notify_update_portal = fields.Boolean(string='Update parent portal with exemption details')
    notify_auto_adjust_pending = fields.Boolean(string='Automatically adjust pending fee amount')

    @api.depends('request_id', 'approved_amount')
    def _compute_financial_impact(self):
        for wizard in self:
            wizard.total_fee_amount = wizard.request_id.total_fee_amount
            wizard.current_pending_amount = wizard.request_id.pending_amount
            wizard.new_pending_amount = max(wizard.request_id.pending_amount - wizard.approved_amount, 0.0)

    @api.onchange('approval_type', 'request_id')
    def _onchange_approval_type(self):
        if self.request_id:
            if self.approval_type == 'full_approval':
                self.exemption_method = (
                    'fixed_amount' if self.request_id.request_value_type == 'amount' else 'percentage')
                self.approved_amount = (
                    self.request_id.requested_amount if self.request_id.request_value_type == 'amount'
                    else self.request_id.pending_amount * self.request_id.requested_percentage / 100.0)

    @api.constrains('approved_amount')
    def _check_approved_amount(self):
        for wizard in self:
            if wizard.approved_amount <= 0:
                raise ValidationError(_('Approved Amount must be greater than zero.'))

    def action_confirm_approve(self):
        self.ensure_one()
        request = self.request_id
        exemption_vals = {
            'request_id': request.id,
            'student_id': request.student_id.id,
            'parent_id': request.parent_id.id,
            'exemption_type': request.exemption_type,
            'category': 'full_exemption' if self.approval_type == 'full_approval' else 'partial_exemption',
            'exemption_method': self.exemption_method,
            'fixed_amount': self.approved_amount if self.exemption_method == 'fixed_amount' else 0.0,
            'coverage_percentage': self.approved_amount if self.exemption_method == 'percentage' else 0.0,
            'max_exemption_amount': self.approved_amount if self.exemption_method == 'fixed_amount' else 0.0,
            'fee_category_scope': self.fee_category_scope,
            'applicable_fee_category_ids': [(6, 0, self.applicable_fee_category_ids.ids)],
            'priority_level': self.priority_level,
            'reason': request.reason,
            'valid_from': self.valid_from,
            'valid_until': self.valid_until,
            'auto_renew': self.auto_renew,
            'approval_status': 'approved',
            'approved_by': self.approved_by.id,
            'approval_date': self.approval_date,
            'approval_notes': self.approval_notes,
            'internal_notes': self.internal_remarks,
            'document_ids': [(6, 0, self.document_ids.ids)],
            'notify_parent': self.notify_parent,
            'notify_sms': self.notify_sms,
            'notify_email': self.notify_parent,
        }
        exemption = self.env['bxi.fee.exemption'].create(exemption_vals)
        request.write({
            'status': 'approved',
            'exemption_id': exemption.id,
            'approved_by': self.approved_by.id,
            'approval_date': self.approval_date,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Fee Exemption'),
            'res_model': 'bxi.fee.exemption',
            'view_mode': 'form',
            'res_id': exemption.id,
        }
