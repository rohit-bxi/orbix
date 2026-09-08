# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

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
