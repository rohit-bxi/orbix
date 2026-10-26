# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import models


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _get_bxi_api_profile(self):
        """What /auth/login and /auth/me return about the caller. Modules
        that know about school roles (bxi_api_support) extend this dict
        with roles and linked student/parent/teacher ids, so the app can
        pick its screens from a single call."""
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'login': self.login,
            'email': self.email,
            'phone': self.phone or None,
            'lang': self.lang,
            'tz': self.tz or None,
            'company': {'id': self.company_id.id, 'name': self.company_id.name},
            'is_admin': self.has_group('base.group_system'),
        }
