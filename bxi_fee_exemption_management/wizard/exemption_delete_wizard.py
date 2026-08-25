from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FeeExemptionDeleteWizard(models.TransientModel):
    _name = 'bxi.fee.exemption.delete.wizard'
    _description = 'Delete Fee Exemption'

    exemption_id = fields.Many2one('bxi.fee.exemption', required=True)

    student_id = fields.Many2one(related='exemption_id.student_id', readonly=True)
    class_id = fields.Many2one(related='exemption_id.class_id', readonly=True)
    name = fields.Char(related='exemption_id.name', string='Exemption ID', readonly=True)
    exemption_type = fields.Selection(related='exemption_id.exemption_type', readonly=True)
    approval_status = fields.Selection(related='exemption_id.approval_status', readonly=True)
    valid_from = fields.Date(related='exemption_id.valid_from', readonly=True)
    valid_until = fields.Date(related='exemption_id.valid_until', readonly=True)
    reason = fields.Text(related='exemption_id.reason', readonly=True)
    currency_id = fields.Many2one(related='exemption_id.currency_id', readonly=True)

    lost_exemption_amount = fields.Monetary(compute='_compute_financial_impact')
    current_pending_amount = fields.Monetary(compute='_compute_financial_impact')
    new_pending_amount = fields.Monetary(compute='_compute_financial_impact')

    confirmation_text = fields.Char(string='Type DELETE to confirm')
    understand_permanent = fields.Boolean(
        string='I understand this will permanently delete this exemption and it cannot be recovered.')
    notify_of_change = fields.Boolean(
        string='I will notify the student and parent/guardian about this change and the updated fee structure.')

    @api.depends('exemption_id')
    def _compute_financial_impact(self):
        for wizard in self:
            wizard.lost_exemption_amount = wizard.exemption_id.exemption_amount
            wizard.current_pending_amount = wizard.exemption_id.net_payable_amount
            wizard.new_pending_amount = wizard.exemption_id.total_fee_amount

    def action_confirm_delete(self):
        self.ensure_one()
        if (self.confirmation_text or '').strip().upper() != 'DELETE':
            raise ValidationError(_('Type DELETE to confirm.'))
        if not (self.understand_permanent and self.notify_of_change):
            raise ValidationError(_('Both confirmation checkboxes must be ticked before deleting.'))
        self.exemption_id.document_ids.unlink()
        self.exemption_id.unlink()
        return {'type': 'ir.actions.act_window_close'}
