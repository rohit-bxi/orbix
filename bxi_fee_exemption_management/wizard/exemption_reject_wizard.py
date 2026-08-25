from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from ..models.fee_exemption_request import REJECTION_REASON_CATEGORIES


class FeeExemptionRejectWizard(models.TransientModel):
    _name = 'bxi.fee.exemption.reject.wizard'
    _description = 'Reject Fee Exemption Request'

    request_id = fields.Many2one('bxi.fee.exemption.request', required=True)

    # Read-only context from the request
    student_id = fields.Many2one(related='request_id.student_id', readonly=True)
    parent_id = fields.Many2one(related='request_id.parent_id', readonly=True)
    class_id = fields.Many2one(related='request_id.class_id', readonly=True)
    exemption_type = fields.Selection(related='request_id.exemption_type', readonly=True)
    requested_amount = fields.Monetary(related='request_id.requested_amount', readonly=True)
    original_reason = fields.Text(related='request_id.reason', string='Original Request Reason', readonly=True)
    currency_id = fields.Many2one(related='request_id.currency_id', readonly=True)

    # Rejection Details
    rejection_reason_category = fields.Selection(REJECTION_REASON_CATEGORIES, required=True)
    detailed_rejection_reason = fields.Text(string='Detailed Rejection Reason (will be sent to parent)', required=True)
    reapplication_suggestions = fields.Text(string='Suggestions for Reapplication (Optional)')
    rejected_by = fields.Many2one('res.users', default=lambda self: self.env.user, required=True)
    rejection_date = fields.Date(default=fields.Date.context_today, required=True)
    internal_notes = fields.Text(string='Internal Notes (Not visible to parent)')

    # Notification Settings
    notify_parent = fields.Boolean(string='Send rejection notification to parent')
    notify_sms = fields.Boolean(string='Send SMS notification')
    notify_update_portal = fields.Boolean(string='Update parent portal with rejection status')
    allow_reapplication = fields.Boolean(string='Allow reapplication after 30 days')

    confirmation_text = fields.Char(string='Type REJECT to confirm')

    def action_confirm_reject(self):
        self.ensure_one()
        if (self.confirmation_text or '').strip().upper() != 'REJECT':
            raise ValidationError(_('Type REJECT to confirm.'))
        self.request_id.write({
            'status': 'rejected',
            'rejection_reason_category': self.rejection_reason_category,
            'rejection_reason': self.detailed_rejection_reason,
            'reapplication_suggestions': self.reapplication_suggestions,
            'rejected_by': self.rejected_by.id,
            'rejection_date': self.rejection_date,
            'allow_reapplication_after_days': 30 if self.allow_reapplication else 0,
            'internal_notes': self.internal_notes,
        })
        return {'type': 'ir.actions.act_window_close'}
