# -*- coding: utf-8 -*-

from odoo import fields, models


class OpStudent(models.Model):
    _inherit = 'op.student'

    enrollment_status = fields.Selection([
        ('new_admission', 'New Admission'),
        ('active', 'Active'),
        ('transferred', 'Transferred'),
        ('alumni', 'Alumni'),
        ('dropped', 'Dropped'),
    ], string='Enrollment Status', default='new_admission', tracking=True)
