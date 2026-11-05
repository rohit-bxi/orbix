# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import models
from odoo.exceptions import AccessDenied


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

    def _bxi_check_step_up(self, payload):
        """Check the confirmation sent to /api/v1/auth/step-up. Returns
        (ok, error_code). Password here; bxi_notification_gateway adds
        `otp` for accounts that only ever log in by phone."""
        self.ensure_one()
        password = payload.get('password') or ''
        if not password:
            return False, 'missing_credentials'
        try:
            self._check_credentials(
                {'login': self.login, 'password': password, 'type': 'password'}, {'interactive': True})
        except AccessDenied:
            return False, 'invalid_credentials'
        return True, None
