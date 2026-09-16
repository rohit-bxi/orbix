# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class CanteenPatronMixin(models.AbstractModel):
    _name = 'bxi.canteen.patron.mixin'
    _description = 'Canteen Record Patron Link'

    student_id = fields.Many2one('op.student', string='Student')
    faculty_id = fields.Many2one('op.faculty', string='Teacher')
    patron_type = fields.Selection([
        ('student', 'Student'),
        ('faculty', 'Teacher'),
    ], string='Patron Type', compute='_compute_patron', store=True)
    patron_name = fields.Char(string='Patron Name', compute='_compute_patron', store=True)

    @api.depends('student_id', 'faculty_id')
    def _compute_patron(self):
        for record in self:
            if record.student_id:
                record.patron_type = 'student'
                record.patron_name = record.student_id.name
            elif record.faculty_id:
                record.patron_type = 'faculty'
                record.patron_name = record.faculty_id.name
            else:
                record.patron_type = False
                record.patron_name = False

    @api.model_create_multi
    def create(self, vals_list):
        # @api.constrains only fires for fields present in vals, so a create() that
        # omits both student_id and faculty_id (e.g. create({})) would otherwise skip
        # _check_single_patron entirely and silently produce a patron-less record.
        records = super().create(vals_list)
        records._check_single_patron()
        return records

    @api.constrains('student_id', 'faculty_id')
    def _check_single_patron(self):
        for record in self:
            if bool(record.student_id) == bool(record.faculty_id):
                raise ValidationError(_('Select exactly one patron: either a Student or a Teacher, not both or neither.'))
