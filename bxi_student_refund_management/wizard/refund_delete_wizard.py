from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class RefundDeleteWizard(models.TransientModel):
    _name = 'bxi.refund.delete.wizard'
    _description = 'Delete Refund Request'

    refund_request_id = fields.Many2one('bxi.student.refund.request', required=True)

    student_id = fields.Many2one(related='refund_request_id.student_id', readonly=True)
    class_id = fields.Many2one(related='refund_request_id.class_id', readonly=True)
    name = fields.Char(related='refund_request_id.name', string='Refund ID', readonly=True)
    refund_type = fields.Selection(related='refund_request_id.refund_type', readonly=True)
    refund_amount = fields.Monetary(related='refund_request_id.refund_amount', readonly=True)
    status = fields.Selection(related='refund_request_id.status', readonly=True)
    request_date = fields.Date(related='refund_request_id.request_date', readonly=True)
    original_payment_mode = fields.Selection(related='refund_request_id.original_payment_mode', readonly=True)
    reason = fields.Text(related='refund_request_id.reason', readonly=True)
    currency_id = fields.Many2one(related='refund_request_id.currency_id', readonly=True)

    document_count = fields.Integer(compute='_compute_impact')
    timeline_event_count = fields.Integer(compute='_compute_impact')

    confirmation_text = fields.Char(string='Type DELETE to confirm')
    understand_permanent = fields.Boolean(
        string='I understand this will permanently delete the refund request and all associated records.')
    notify_parent_of_deletion = fields.Boolean(
        string='I will notify the parent/guardian that this refund request has been cancelled.')

    @api.depends('refund_request_id')
    def _compute_impact(self):
        for wizard in self:
            wizard.document_count = len(wizard.refund_request_id.document_ids)
            wizard.timeline_event_count = len(wizard.refund_request_id.message_ids)

    def action_confirm_delete(self):
        self.ensure_one()
        if (self.confirmation_text or '').strip().upper() != 'DELETE':
            raise ValidationError(_('Type DELETE to confirm.'))
        if not (self.understand_permanent and self.notify_parent_of_deletion):
            raise ValidationError(_('Both confirmation checkboxes must be ticked before deleting.'))
        self.refund_request_id.document_ids.unlink()
        self.refund_request_id.unlink()
        return {'type': 'ir.actions.act_window_close'}
