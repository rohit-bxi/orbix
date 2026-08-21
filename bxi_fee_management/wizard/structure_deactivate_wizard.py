from odoo import _, fields, models
from odoo.exceptions import UserError


class FeeStructureDeactivateWizard(models.TransientModel):
    _name = 'bxi.fee.structure.deactivate.wizard'
    _description = 'Deactivate Fee Structure'

    structure_id = fields.Many2one('op.fees.terms', required=True)
    name = fields.Char(related='structure_id.name', readonly=True)
    academic_year_id = fields.Many2one(related='structure_id.academic_year_id', readonly=True)
    currency_id = fields.Many2one(related='structure_id.currency_id', readonly=True)
    total_amount = fields.Monetary(related='structure_id.total_amount', readonly=True)
    assigned_student_count = fields.Integer(related='structure_id.assigned_student_count', readonly=True)
    active_payment_count = fields.Integer(related='structure_id.active_payment_count', readonly=True)
    pending_payment_count = fields.Integer(related='structure_id.pending_payment_count', readonly=True)

    ack_impact = fields.Boolean(string='I understand the impact of changing the status to inactive')
    ack_reviewed = fields.Boolean(string='I have reviewed the affected students and payments')

    def action_confirm(self):
        self.ensure_one()
        if not (self.ack_impact and self.ack_reviewed):
            raise UserError(_('Please confirm both acknowledgements before deactivating this fee structure.'))
        self.structure_id.action_set_inactive()
        return {'type': 'ir.actions.act_window_close'}
