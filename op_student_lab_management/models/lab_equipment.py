# -*- coding: utf-8 -*-
from odoo import models, fields, api


class LabEquipment(models.Model):
    _name = 'lab.equipment'
    _description = 'Lab Equipment'
    _rec_name = 'name'

    name = fields.Char(string='Equipment Name', required=True)
    code = fields.Char(string='Equipment Code', copy=False)
    lab_id = fields.Many2one('lab.room', string='Lab Room', required=True, ondelete='cascade')
    quantity_total = fields.Integer(string='Total Quantity', default=1, required=True)
    quantity_issued = fields.Integer(compute='_compute_quantity_available', string='Issued Quantity', store=True)
    quantity_available = fields.Integer(compute='_compute_quantity_available', string='Available Quantity', store=True)
    condition = fields.Selection([
        ('good', 'Good'),
        ('damaged', 'Damaged'),
        ('under_repair', 'Under Repair'),
    ], string='Condition', default='good')
    active = fields.Boolean(default=True)

    @api.depends('quantity_total', 'issue_ids.issued_qty', 'issue_ids.returned_qty', 'issue_ids.state')
    def _compute_quantity_available(self):
        for rec in self:
            issued = sum(
                line.issued_qty - line.returned_qty
                for line in rec.issue_ids
                if line.state in ('issued', 'partial')
            )
            rec.quantity_issued = issued
            rec.quantity_available = rec.quantity_total - issued

    issue_ids = fields.One2many('lab.equipment.issue', 'equipment_id', string='Issue Log')
