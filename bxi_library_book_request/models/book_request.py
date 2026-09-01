# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BxiLibraryBookRequest(models.Model):
    _name = 'bxi.library.book.request'
    _description = 'Library Book Request'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    name = fields.Char(string='Request ID', copy=False, readonly=True, default=lambda self: _('New'))
    requester_user_id = fields.Many2one('res.users', string='Requested By', required=True, readonly=True)
    teacher_id = fields.Many2one('op.faculty', string='Teacher')
    media_id = fields.Many2one('op.media', string='Book / Resource', required=True, tracking=True)
    reason = fields.Text()
    status = fields.Selection([
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='pending', required=True, tracking=True)
    reviewed_by = fields.Many2one('res.users', readonly=True, copy=False)
    reviewed_at = fields.Datetime(readonly=True, copy=False)
    review_notes = fields.Text(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.library.book.request') or _('New')
        return super().create(vals_list)

    def action_approve(self, notes=None):
        for request in self:
            if request.status != 'pending':
                raise UserError(_('Only a pending request can be approved.'))
            request.write({
                'status': 'approved', 'reviewed_by': self.env.user.id,
                'reviewed_at': fields.Datetime.now(), 'review_notes': notes,
            })

    def action_reject(self, notes=None):
        for request in self:
            if request.status != 'pending':
                raise UserError(_('Only a pending request can be rejected.'))
            request.write({
                'status': 'rejected', 'reviewed_by': self.env.user.id,
                'reviewed_at': fields.Datetime.now(), 'review_notes': notes,
            })
