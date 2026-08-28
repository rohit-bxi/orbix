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
        sourced from posted invoices only. Used to surface
        overpayment/pending amounts for refunds without ever writing to the
        invoicing engine.

        Reads all posted customer invoices on the student's partner
        directly, rather than only invoices reachable through
        ``fees_detail_ids`` - that relation is populated solely by
        bxi_fee_management's own Fee Structure flow, so relying on it alone
        silently drops invoices created any other way (e.g. openeducat_fees'
        native flow, admission fees, or manual invoicing) and understates
        both paid and pending amounts.
        """
        self.ensure_one()
        invoices = self.env['account.move'].search([
            ('partner_id', '=', self.partner_id.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
        ])
        total_fee = sum(invoices.mapped('amount_total'))
        # Sum actual posted customer payments rather than amount_total -
        # amount_residual per invoice: when a payment exceeds an invoice's
        # total, Odoo floors that invoice's amount_residual at 0 instead of
        # going negative, so the residual-based math silently undercounts
        # genuine overpayments (the exact case a refund request exists for).
        payments = self.env['account.payment'].search([
            ('partner_id', '=', self.partner_id.id),
            ('payment_type', '=', 'inbound'),
            ('state', 'in', ('paid', 'in_process')),
        ])
        total_paid = sum(payments.mapped('amount'))
        return {
            'total_fee_amount': total_fee,
            'total_paid_amount': total_paid,
            'excess_amount': max(total_paid - total_fee, 0.0),
            'pending_amount': max(total_fee - total_paid, 0.0),
        }
