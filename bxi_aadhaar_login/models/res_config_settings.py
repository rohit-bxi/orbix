# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    bxi_aadhaar_login_enabled = fields.Boolean(
        related='company_id.bxi_aadhaar_login_enabled', readonly=False)
    bxi_aadhaar_login_otp_enabled = fields.Boolean(
        related='company_id.bxi_aadhaar_login_otp_enabled', readonly=False)
    bxi_aadhaar_login_requires_verified = fields.Boolean(
        related='company_id.bxi_aadhaar_login_requires_verified', readonly=False)
    bxi_aadhaar_login_allow_student = fields.Boolean(
        related='company_id.bxi_aadhaar_login_allow_student', readonly=False)
    bxi_aadhaar_login_allow_teacher = fields.Boolean(
        related='company_id.bxi_aadhaar_login_allow_teacher', readonly=False)
    bxi_aadhaar_login_allow_parent = fields.Boolean(
        related='company_id.bxi_aadhaar_login_allow_parent', readonly=False)
    bxi_aadhaar_login_otp_in_response = fields.Boolean(
        string='Show Login Code in API Response (Testing)', config_parameter='bxi_aadhaar_login.otp_in_response',
        help='Testing only: /api/v1/auth/aadhaar/otp-request also returns the code. Anyone who knows an Aadhaar '
             'number can then log in as that person. Keep it off with real students, teachers and parents.')
