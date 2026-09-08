# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Para 6.6-6.10 / 8.3-8.7: a parent dissatisfied with document verification
# can file an online grievance with the school's CBEO, who must resolve it
# within 5 days (para 6.7/8.4); an unresolved/rejected grievance escalates
# to the JD (Joint Director) level.
RTE_GRIEVANCE_STATES = [
    ('draft', 'Draft'),
    ('submitted', 'Submitted to CBEO'),
    ('escalated_jd', 'Escalated to Joint Director'),
    ('resolved', 'Resolved'),
    ('rejected', 'Rejected'),
]


class RteGrievance(models.Model):
    _name = 'rte.grievance'
    _description = 'RTE Document Verification Grievance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Grievance Number', required=True, copy=False, readonly=True,
        default=lambda self: _('New'))
    admission_id = fields.Many2one(
        'op.admission', string='Admission', required=True,
        domain=[('is_rte_applicant', '=', True)], tracking=True,
        ondelete='cascade')
    description = fields.Text(
        string='Grievance Details', required=True,
        help='What the parent is dissatisfied with about the document '
             'verification decision (para 6.6/8.3). No new documents may '
             'be submitted with a grievance -- it is decided on the '
             'documents already on file (para 6.6/8.3).')
    state = fields.Selection(
        RTE_GRIEVANCE_STATES, string='Status', default='draft',
        required=True, tracking=True)
    cbeo_resolution_notes = fields.Text(string='CBEO Resolution Notes')
    jd_resolution_notes = fields.Text(string='Joint Director Resolution Notes')

    def action_submit(self):
        for grievance in self:
            if grievance.state != 'draft':
                raise UserError(_('Only Draft grievances can be submitted.'))
            grievance.write({'state': 'submitted'})
            grievance.message_post(body=_('Grievance submitted to CBEO.'))

    def action_cbeo_resolve(self):
        for grievance in self:
            if grievance.state != 'submitted':
                raise UserError(_(
                    'Only a grievance Submitted to CBEO can be resolved '
                    'at CBEO level.'))
            if not grievance.cbeo_resolution_notes:
                raise UserError(_(
                    'Please record the CBEO resolution notes (para 6.7/8.4).'))
            grievance.write({'state': 'resolved'})
            grievance.message_post(body=_(
                'Grievance resolved by CBEO: %s') % grievance.cbeo_resolution_notes)

    def action_escalate_to_jd(self):
        """Para 6.8/8.5: a grievance the CBEO cannot resolve is forwarded
        to the JD/District Education Officer level."""
        for grievance in self:
            if grievance.state != 'submitted':
                raise UserError(_(
                    'Only a grievance Submitted to CBEO can be escalated.'))
            grievance.write({'state': 'escalated_jd'})
            grievance.message_post(body=_(
                'Grievance escalated to Joint Director (para 6.8/8.5).'))

    def action_jd_resolve(self):
        for grievance in self:
            if grievance.state != 'escalated_jd':
                raise UserError(_(
                    'Only an Escalated grievance can be resolved at Joint '
                    'Director level.'))
            if not grievance.jd_resolution_notes:
                raise UserError(_(
                    'Please record the Joint Director resolution notes '
                    '(para 6.10/8.7).'))
            grievance.write({'state': 'resolved'})
            grievance.message_post(body=_(
                'Grievance resolved by Joint Director: %s')
                % grievance.jd_resolution_notes)

    def action_reject(self):
        for grievance in self:
            if grievance.state not in ('submitted', 'escalated_jd'):
                raise UserError(_(
                    'Only a Submitted or Escalated grievance can be '
                    'rejected.'))
            grievance.write({'state': 'rejected'})
            grievance.message_post(body=_('Grievance rejected.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'rte.grievance') or _('New')
        return super().create(vals_list)
