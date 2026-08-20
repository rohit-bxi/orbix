from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ScholarshipRemoveWizard(models.TransientModel):
    _name = 'bxi.scholarship.remove.wizard'
    _description = 'Remove Student Scholarship'

    scholarship_id = fields.Many2one('bxi.student.scholarship', required=True)

    student_id = fields.Many2one(related='scholarship_id.student_id', readonly=True)
    class_id = fields.Many2one(related='scholarship_id.class_id', readonly=True)
    scholarship_type = fields.Selection(related='scholarship_id.scholarship_type', readonly=True)
    program_id = fields.Many2one(related='scholarship_id.program_id', readonly=True)
    name = fields.Char(related='scholarship_id.name', string='Reference Code', readonly=True)
    academic_year_id = fields.Many2one(related='scholarship_id.academic_year_id', readonly=True)
    coverage_percentage = fields.Float(related='scholarship_id.coverage_percentage', readonly=True)
    approval_status = fields.Selection(related='scholarship_id.approval_status', readonly=True)
    valid_from = fields.Date(related='scholarship_id.valid_from', readonly=True)
    valid_until = fields.Date(related='scholarship_id.valid_until', readonly=True)
    currency_id = fields.Many2one(related='scholarship_id.currency_id', readonly=True)

    lost_scholarship_amount = fields.Monetary(compute='_compute_financial_impact')
    current_pending_amount = fields.Monetary(compute='_compute_financial_impact')
    new_pending_amount = fields.Monetary(compute='_compute_financial_impact')

    confirmation_text = fields.Char(string='Type REMOVE to confirm')

    @api.depends('scholarship_id')
    def _compute_financial_impact(self):
        for wizard in self:
            wizard.lost_scholarship_amount = wizard.scholarship_id.scholarship_amount
            wizard.current_pending_amount = wizard.scholarship_id.net_payable_amount
            wizard.new_pending_amount = wizard.scholarship_id.total_fee_amount

    def action_confirm_remove(self):
        self.ensure_one()
        if (self.confirmation_text or '').strip().upper() != 'REMOVE':
            raise ValidationError(_('Type REMOVE to confirm removal of this scholarship.'))
        self.scholarship_id.active = False
        return {'type': 'ir.actions.act_window_close'}
