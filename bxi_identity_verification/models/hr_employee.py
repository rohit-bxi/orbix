# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, models

HR_USER = 'hr.group_hr_user'


class HrEmployee(models.Model):
    """Aadhaar (and ID verification) for staff - administrators and office
    staff, who have an employee record but no student/teacher/parent one.
    Aadhaar login uses it for the 'staff' role (bxi_aadhaar_login)."""
    _name = 'hr.employee'
    _inherit = ['hr.employee', 'bxi.identity.verification.mixin']

    id_document_ids = fields.Many2many(
        'ir.attachment', 'hr_employee_id_document_rel', 'employee_id', 'attachment_id', string='ID Documents',
        groups=HR_USER, help='Scanned ID proof (image or PDF) sent for verification.')

    # Private identity data: not on the public employee profile
    # (hr.employee.public), so - as hr.employee requires of such fields -
    # limited to HR users. Otherwise a login without HR rights (a teacher
    # opening Time Off, /api/v1/leaves) prefetches them and hr.employee
    # refuses the whole read. The identity, Aadhaar-login and people APIs
    # read them with sudo. aadhar_card and bxi_aadhaar_hash keep their own,
    # stricter groups from the mixin.
    bxi_aadhaar_last4 = fields.Char(groups=HR_USER)
    aadhar_verification_status = fields.Selection(groups=HR_USER)
    aadhar_submitted_at = fields.Datetime(groups=HR_USER)
    aadhar_verified_at = fields.Datetime(groups=HR_USER)
    aadhar_verification_notes = fields.Text(groups=HR_USER)
    face_verification_status = fields.Selection(groups=HR_USER)
    face_submitted_at = fields.Datetime(groups=HR_USER)
    face_verified_at = fields.Datetime(groups=HR_USER)
    id_document_status = fields.Selection(groups=HR_USER)
    id_document_type = fields.Selection(groups=HR_USER)
    id_document_submitted_at = fields.Datetime(groups=HR_USER)
    id_document_verified_at = fields.Datetime(groups=HR_USER)
    id_document_notes = fields.Text(groups=HR_USER)

    def _bxi_aadhaar_partner(self):
        self.ensure_one()
        return self.work_contact_id
