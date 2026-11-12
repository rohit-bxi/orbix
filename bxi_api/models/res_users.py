# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

import secrets
import string
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied

# Letters and digits without the look-alikes (O/0, I/l/1) - the person
# often types it from an SMS.
TEMP_PASSWORD_ALPHABET = ''.join(c for c in string.ascii_letters + string.digits if c not in 'O0Il1')
TEMP_PASSWORD_LENGTH = 10
DEFAULT_TEMP_PASSWORD_HOURS = 72
MIN_PASSWORD_LENGTH = 8


class ResUsers(models.Model):
    _inherit = 'res.users'

    bxi_must_change_password = fields.Boolean(
        string='Must Change Password', copy=False, readonly=True,
        help='The current password is a one-time password set by the school office. Until the person '
             'changes it, the app API only allows changing the password.')
    bxi_temp_password_expires_at = fields.Datetime(
        string='One-Time Password Expires At', copy=False, readonly=True,
        help='After this moment the one-time password no longer signs in; the office issues a new one.')

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
            'must_change_password': self.sudo().bxi_must_change_password,
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

    # -- one-time passwords ----------------------------------------------------------

    @api.model
    def _bxi_password_min_length(self):
        policy = self.env['ir.config_parameter'].sudo().get_param('auth_password_policy.minlength') or 0
        try:
            policy = int(policy)
        except ValueError:
            policy = 0
        return max(MIN_PASSWORD_LENGTH, policy)

    @api.model
    def _bxi_password_problem(self, password):
        """Why `password` can't be used as a new password, or None."""
        if not isinstance(password, str) or not password.strip():
            return _('A password is required.')
        minimum = self._bxi_password_min_length()
        if len(password.strip()) < minimum:
            return _('The password must be at least %s characters long.', minimum)
        return None

    @api.model
    def _bxi_generate_password(self):
        return ''.join(secrets.choice(TEMP_PASSWORD_ALPHABET) for _i in range(TEMP_PASSWORD_LENGTH))

    def _bxi_set_temporary_password(self, password=None):
        """Give this account a one-time password - `password` when the
        office typed one, else a generated one - that must be changed at
        the next sign-in and stops working after
        `bxi_api.temp_password_hours` (default 72). Signs the account out
        of every app session. Returns the password."""
        self.ensure_one()
        password = (password or '').strip() or self._bxi_generate_password()
        hours = self.env['ir.config_parameter'].sudo().get_param('bxi_api.temp_password_hours')
        try:
            hours = int(hours or DEFAULT_TEMP_PASSWORD_HOURS)
        except ValueError:
            hours = DEFAULT_TEMP_PASSWORD_HOURS
        self.sudo().with_context(bxi_temporary_password=True).write({
            'password': password,
            'bxi_must_change_password': True,
            'bxi_temp_password_expires_at': fields.Datetime.now() + timedelta(hours=hours) if hours > 0 else False,
        })
        self.env['bxi.api.token'].sudo()._revoke_all_for_user(self)
        return password

    def write(self, vals):
        res = super().write(vals)
        if 'password' in vals and not self.env.context.get('bxi_temporary_password'):
            # The person chose their own password: the one-time one is gone.
            # A separate sudo write, so the flag is never self-writable.
            self.sudo().filtered('bxi_must_change_password').write({
                'bxi_must_change_password': False, 'bxi_temp_password_expires_at': False,
            })
        return res

    def _check_credentials(self, credential, env):
        auth_info = super()._check_credentials(credential, env)
        if credential.get('type') == 'password':
            user = self.sudo()
            if user.bxi_must_change_password and user.bxi_temp_password_expires_at \
                    and user.bxi_temp_password_expires_at < fields.Datetime.now():
                raise AccessDenied(_('This one-time password has expired. Ask the school office for a new one.'))
        return auth_info
