# -*- coding: utf-8 -*-

from odoo import _, fields, models
from odoo.exceptions import UserError


class RteDocumentVerifyWizard(models.TransientModel):
    _name = 'rte.document.verify.wizard'
    _description = 'RTE Document Verify Wizard'

    admission_id = fields.Many2one(
        'op.admission', string='Admission', required=True,
        default=lambda self: self.env.context.get('active_id'))
    action_type = fields.Selection([
        ('verify', 'Verify Documents'),
        ('reject', 'Reject Documents'),
    ], string='Action', required=True, default='verify')
    rejection_reason = fields.Text(string='Rejection Reason')

    def action_confirm(self):
        self.ensure_one()
        if self.action_type == 'verify':
            self.admission_id.action_verify_documents()
        else:
            if not self.rejection_reason:
                raise UserError(_('Please provide a rejection reason.'))
            self.admission_id.rejection_reason = self.rejection_reason
            self.admission_id.action_reject_documents()
        return {'type': 'ir.actions.act_window_close'}
