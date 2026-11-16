# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, models


class HrEmployee(models.Model):
    """Aadhaar (and ID verification) for staff - administrators and office
    staff, who have an employee record but no student/teacher/parent one.
    Aadhaar login uses it for the 'staff' role (bxi_aadhaar_login)."""
    _name = 'hr.employee'
    _inherit = ['hr.employee', 'bxi.identity.verification.mixin']

    id_document_ids = fields.Many2many(
        'ir.attachment', 'hr_employee_id_document_rel', 'employee_id', 'attachment_id', string='ID Documents',
        help='Scanned ID proof (image or PDF) sent for verification.')

    def _bxi_aadhaar_partner(self):
        self.ensure_one()
        return self.work_contact_id
