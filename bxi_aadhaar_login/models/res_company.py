# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, models

# Record model -> role name used by the settings and the API.
ROLE_BY_MODEL = {'op.student': 'student', 'op.faculty': 'teacher', 'op.parent': 'parent', 'hr.employee': 'staff'}
ROLES = ('student', 'teacher', 'parent', 'staff')


class ResCompany(models.Model):
    """Aadhaar login settings, per school (company)."""
    _inherit = 'res.company'

    bxi_aadhaar_login_enabled = fields.Boolean(
        string='Aadhaar Login', default=True,
        help='Students, teachers and parents may log in with their Aadhaar number instead of their username.')
    bxi_aadhaar_login_otp_enabled = fields.Boolean(
        string='Aadhaar Login by Email Code', default=True,
        help='Besides the password, a one-time code emailed to the address on the school record '
             'can be used. Needs an outgoing mail server.')
    bxi_aadhaar_login_requires_verified = fields.Boolean(
        string='Verified Aadhaar Only', default=True,
        help='Only numbers typed by the school office, or verified by an Identity Reviewer, can be used '
             'to log in. A number the family submitted from the app waits for review.')
    bxi_aadhaar_login_allow_student = fields.Boolean(string='Aadhaar Login for Students', default=True)
    bxi_aadhaar_login_allow_teacher = fields.Boolean(string='Aadhaar Login for Teachers', default=True)
    bxi_aadhaar_login_allow_parent = fields.Boolean(string='Aadhaar Login for Parents', default=True)
    bxi_aadhaar_login_allow_staff = fields.Boolean(
        string='Aadhaar Login for Staff & Administrators', default=False,
        help='Administrators and office staff, with the Aadhaar number on their employee record '
             '(Employees > Identity Verification). Off by default.')

    def _bxi_aadhaar_role_allowed(self, role):
        self.ensure_one()
        return bool(self[f'bxi_aadhaar_login_allow_{role}'])

    def _bxi_aadhaar_settings(self):
        self.ensure_one()
        return {
            'enabled': self.bxi_aadhaar_login_enabled,
            'otp_enabled': self.bxi_aadhaar_login_otp_enabled,
            'requires_verified': self.bxi_aadhaar_login_requires_verified,
            'roles': [role for role in ROLES if self._bxi_aadhaar_role_allowed(role)],
        }
