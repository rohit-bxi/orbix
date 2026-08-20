from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class RefundBulkWizard(models.TransientModel):
    _name = 'bxi.refund.bulk.wizard'
    _description = 'Bulk Refund Processing'

    class_id = fields.Many2one('op.course', string='Class')
    section_id = fields.Many2one('op.batch', string='Section')
    student_ids = fields.Many2many('op.student', string='Select Students')

    refund_type = fields.Selection([
        ('fee_overpayment', 'Fee Overpayment'),
        ('withdrawal', 'Withdrawal Refund'),
        ('transport_fee', 'Transport Fee Refund'),
        ('exam_fee', 'Exam Fee Refund'),
        ('activity_fee', 'Activity Fee Refund'),
        ('lab_fee', 'Lab Fee Refund'),
        ('special_circumstances', 'Special Circumstances'),
        ('other', 'Other'),
    ], required=True, default='fee_overpayment')
    refund_amount_calculation = fields.Selection([
        ('percentage_of_excess', 'Percentage of total amount'),
        ('full_excess_amount', 'Full excess amount'),
        ('fixed_amount', 'Fixed amount'),
    ], required=True, default='percentage_of_excess')
    refund_percentage = fields.Float(default=100.0)
    fixed_refund_amount = fields.Monetary()

    priority = fields.Selection([
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
    ], default='normal')
    request_date = fields.Date(required=True, default=fields.Date.context_today)
    reason = fields.Text(string='Reason for Refund (Common for All)')

    preferred_refund_mode = fields.Selection([
        ('bank_transfer', 'Bank Transfer (NEFT/RTGS)'),
        ('upi', 'UPI'),
        ('cash', 'Cash'),
        ('cheque', 'Cheque'),
    ])
    processing_status = fields.Selection([
        ('draft', 'Draft'),
        ('pending_review', 'Pending Review'),
    ], default='pending_review', string='Initial Processing Status')

    document_ids = fields.Many2many(
        comodel_name='ir.attachment',
        relation='bxi_refund_bulk_document_rel',
        column1='wizard_id', column2='attachment_id',
        string='Supporting Documents (Common for All)')

    notify_parent = fields.Boolean(string='Notify all parents/guardians about refund requests')
    notify_sms = fields.Boolean(string='Send SMS notification')
    notify_email = fields.Boolean(string='Send email notification')
    notify_auto_update = fields.Boolean(string='Auto-update on status change')

    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    total_students_with_excess = fields.Integer(compute='_compute_stats')
    selected_count = fields.Integer(compute='_compute_stats')
    total_refund_amount = fields.Monetary(compute='_compute_stats')
    available_for_refund = fields.Monetary(compute='_compute_stats')

    def _eligible_students_domain(self):
        domain = []
        if self.class_id:
            domain.append(('course_detail_ids.course_id', '=', self.class_id.id))
        if self.section_id:
            domain.append(('course_detail_ids.batch_id', '=', self.section_id.id))
        return domain

    def _student_refund_amount(self, excess_amount):
        if self.refund_amount_calculation == 'full_excess_amount':
            return excess_amount
        if self.refund_amount_calculation == 'fixed_amount':
            return self.fixed_refund_amount
        return excess_amount * (self.refund_percentage / 100.0)

    @api.depends('class_id', 'section_id', 'student_ids', 'refund_amount_calculation',
                 'refund_percentage', 'fixed_refund_amount')
    def _compute_stats(self):
        for wizard in self:
            candidates = self.env['op.student'].search(wizard._eligible_students_domain())
            eligible = candidates.filtered(lambda s: s.get_fee_payment_summary()['excess_amount'] > 0)
            wizard.total_students_with_excess = len(eligible)
            wizard.available_for_refund = sum(
                s.get_fee_payment_summary()['excess_amount'] for s in eligible)
            wizard.selected_count = len(wizard.student_ids)
            wizard.total_refund_amount = sum(
                wizard._student_refund_amount(s.get_fee_payment_summary()['excess_amount'])
                for s in wizard.student_ids)

    def action_process_refunds(self):
        self.ensure_one()
        if not self.student_ids:
            raise ValidationError(_('Select at least one student.'))
        Refund = self.env['bxi.student.refund.request']
        created = Refund
        for student in self.student_ids:
            excess = student.get_fee_payment_summary()['excess_amount']
            if excess <= 0:
                raise ValidationError(_('%s has no excess payment to refund.') % student.name)
            created |= Refund.create({
                'student_id': student.id,
                'parent_id': student.parent_ids[:1].id,
                'refund_type': self.refund_type,
                'refund_amount': self._student_refund_amount(excess),
                'priority': self.priority,
                'request_date': self.request_date,
                'reason': self.reason,
                'preferred_refund_mode': self.preferred_refund_mode,
                'status': self.processing_status,
                'document_ids': [(6, 0, self.document_ids.ids)],
                'notify_parent': self.notify_parent,
                'notify_sms': self.notify_sms,
                'notify_email': self.notify_email,
                'notify_auto_update': self.notify_auto_update,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Refund Requests'),
            'res_model': 'bxi.student.refund.request',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
        }
