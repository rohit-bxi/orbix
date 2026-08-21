# -*- coding: utf-8 -*-
from odoo import models, fields, api


class LabRoom(models.Model):
    _name = 'lab.room'
    _description = 'Lab Room'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'

    name = fields.Char(string='Lab Name', required=True, tracking=True)
    code = fields.Char(string='Lab Code', required=True, copy=False, tracking=True)
    department_id = fields.Many2one('op.department', string='Department')
    capacity = fields.Integer(string='Capacity', default=30)
    lab_type = fields.Selection([
        ('computer', 'Computer'),
        ('chemistry', 'Chemistry'),
        ('physics', 'Physics'),
        ('biology', 'Biology'),
        ('other', 'Other'),
    ], string='Lab Type', default='computer', required=True)
    instructor_id = fields.Many2one('op.faculty', string='Default Instructor')
    equipment_ids = fields.One2many('lab.equipment', 'lab_id', string='Equipment')
    session_ids = fields.One2many('lab.session', 'room_id', string='Sessions')
    session_count = fields.Integer(compute='_compute_session_count', string='Sessions')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    _code_uniq = models.Constraint(
        'unique(code)', 'Lab code must be unique!',
    )

    def _compute_session_count(self):
        for rec in self:
            rec.session_count = len(rec.session_ids)
