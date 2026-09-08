# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class RteReimbursementClaim(models.Model):
    _name = 'rte.reimbursement.claim'
    _description = 'RTE Reimbursement Claim'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Claim Number', required=True, copy=False, readonly=True,
        default=lambda self: _('New'))
    course_id = fields.Many2one(
        'op.course', string='Course', required=True, tracking=True)
    academic_year_id = fields.Many2one(
        'op.academic.year', string='Academic Year', required=True, tracking=True)
    admission_id = fields.Many2one(
        'op.admission', string='Admission',
        domain=[('is_rte_applicant', '=', True)], tracking=True)
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        related='course_id.currency_id', readonly=True)
    actual_fee_charged = fields.Monetary(
        string='Actual Fee Charged For This Seat', currency_field='currency_id',
        help='The fee the school actually charges a fee-paying student for '
             'an equivalent seat this session. Reimbursement is capped at '
             'the lower of this amount and the course\'s configured '
             'Reimbursement Rate (para 12(2)/Appendix-1) -- amounts '
             'collected as a labelled donation/charity do not count '
             'towards this figure and are never reimbursable.')
    installment = fields.Selection([
        ('first', 'First Installment'),
        ('second', 'Second Installment'),
    ], string='Installment', default='first', required=True,
        help='Reimbursement is paid in two installments. If the child '
             'drops out on or before 31 August of the academic year, only '
             'the first installment is payable (Appendix-4 Q1).')
    amount = fields.Monetary(
        string='Claim Amount', currency_field='currency_id', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', required=True, tracking=True)
    account_move_id = fields.Many2one(
        'account.move', string='Journal Entry', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'rte.reimbursement.claim') or _('New')
        return super().create(vals_list)

    def action_submit(self):
        for claim in self:
            if claim.state != 'draft':
                raise UserError(_('Only Draft claims can be submitted.'))
            if claim.admission_id.rte_is_voluntary_transfer:
                raise UserError(_(
                    'This admission was voluntarily transferred to another '
                    'school and has forfeited further fee reimbursement '
                    '(Appendix-1).'))
            if claim.actual_fee_charged:
                entitlement = min(
                    v for v in (claim.course_id.reimbursement_rate,
                                claim.actual_fee_charged) if v)
                if claim.amount > entitlement:
                    raise UserError(_(
                        'The claim amount (%s) exceeds the reimbursable '
                        'entitlement of %s -- the lower of the course\'s '
                        'Reimbursement Rate and the Actual Fee Charged '
                        '(para 12(2)/Appendix-1).') % (claim.amount, entitlement))
            dropout_date = claim.admission_id.rte_dropout_date
            if (claim.installment == 'second' and dropout_date
                    and claim.academic_year_id.start_date
                    and dropout_date <= claim.academic_year_id.start_date.replace(
                        month=8, day=31)):
                raise UserError(_(
                    'This child dropped out on or before 31 August of the '
                    'academic year (%s) -- only the first installment is '
                    'reimbursable (Appendix-4 Q1).') % dropout_date)
            claim.write({'state': 'submitted'})
            claim.message_post(body=_('Reimbursement claim submitted.'))

    def action_approve(self):
        for claim in self:
            if claim.state != 'submitted':
                raise UserError(_('Only Submitted claims can be approved.'))
            claim.write({'state': 'approved'})
            claim.message_post(body=_('Reimbursement claim approved by %s.')
                                % self.env.user.name)

    def action_reject(self):
        for claim in self:
            if claim.state not in ('submitted', 'approved'):
                raise UserError(_(
                    'Only Submitted or Approved claims can be rejected.'))
            claim.write({'state': 'rejected'})
            claim.message_post(body=_('Reimbursement claim rejected by %s.')
                                % self.env.user.name)

    def action_mark_paid(self):
        for claim in self:
            if claim.state != 'approved':
                raise UserError(_('Only Approved claims can be marked Paid.'))
            claim.write({'state': 'paid'})
            claim.message_post(body=_(
                'Reimbursement claim marked Paid by %s. Amount: %s')
                % (self.env.user.name, claim.amount))
