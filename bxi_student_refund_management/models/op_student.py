from odoo import api, fields, models


class OpStudent(models.Model):
    _inherit = 'op.student'

    refund_request_ids = fields.One2many('bxi.student.refund.request', 'student_id', string='Refund Requests')
    refund_request_count = fields.Integer(compute='_compute_refund_request_count')

    @api.depends('refund_request_ids')
    def _compute_refund_request_count(self):
        for student in self:
            student.refund_request_count = len(student.refund_request_ids)

    def action_view_refund_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Refund Requests',
            'res_model': 'bxi.student.refund.request',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }

    def get_fee_payment_summary(self):
        """Read-only snapshot of a student's real fee vs. paid amounts,
        sourced from posted invoices only (openeducat_fees). Used to
        surface overpayment/pending amounts for refunds without ever
        writing to the invoicing engine.
        """
        self.ensure_one()
        details = self.fees_detail_ids.filtered(lambda d: d.invoice_id and d.invoice_id.state == 'posted')
        invoices = details.invoice_id
        total_fee = sum(invoices.mapped('amount_total'))
        total_paid = sum(invoice.amount_total - invoice.amount_residual for invoice in invoices)
        return {
            'total_fee_amount': total_fee,
            'total_paid_amount': total_paid,
            'excess_amount': max(total_paid - total_fee, 0.0),
            'pending_amount': max(total_fee - total_paid, 0.0),
        }
