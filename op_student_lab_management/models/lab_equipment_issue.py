# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class LabEquipmentIssue(models.Model):
    _name = 'lab.equipment.issue'
    _description = 'Lab Equipment Issue/Return Log'
    _rec_name = 'equipment_id'

    session_id = fields.Many2one('lab.session', string='Session', required=True, ondelete='cascade')
    equipment_id = fields.Many2one('lab.equipment', string='Equipment', required=True)
    student_id = fields.Many2one('op.student', string='Student (optional)')
    issued_qty = fields.Integer(string='Issued Qty', default=1, required=True)
    returned_qty = fields.Integer(string='Returned Qty', default=0)
    issue_date = fields.Date(string='Issue Date', default=fields.Date.context_today)
    return_date = fields.Date(string='Return Date')
    state = fields.Selection([
        ('issued', 'Issued'),
        ('partial', 'Partially Returned'),
        ('returned', 'Returned'),
        ('damaged', 'Damaged'),
    ], string='Status', default='issued', required=True)

    @api.constrains('issued_qty', 'equipment_id')
    def _check_availability(self):
        for rec in self:
            if rec.issued_qty > rec.equipment_id.quantity_available + (
                rec._origin.issued_qty if rec._origin else 0
            ):
                raise ValidationError(_(
                    'Cannot issue %s units of "%s". Only %s units available.'
                ) % (rec.issued_qty, rec.equipment_id.name, rec.equipment_id.quantity_available))

    def action_return(self):
        for rec in self:
            rec.return_date = fields.Date.context_today(rec)
            if rec.returned_qty >= rec.issued_qty:
                rec.state = 'returned'
            elif rec.returned_qty > 0:
                rec.state = 'partial'

    def action_mark_damaged(self):
        self.write({'state': 'damaged'})
