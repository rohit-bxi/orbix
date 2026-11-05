# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

import hashlib
import secrets
from datetime import timedelta

from odoo import api, fields, models

# How long a password/OTP confirmation counts as "recent" for routes that
# need one (see require_step_up / require_recent_auth in controllers/auth.py).
STEP_UP_MINUTES = 10


class BxiApiToken(models.Model):
    """Opaque bearer token issued to a res.users, used by the Orbix mobile
    app instead of Odoo's session cookies (the app is not a browser).

    Only the SHA-256 hash of the token is stored - the raw token is
    returned to the caller once, at issue time, the same way a GitHub
    personal access token works. A database leak of this table does not
    hand out usable tokens.
    """
    _name = 'bxi.api.token'
    _description = 'Orbix API Access Token'
    _order = 'create_date desc'

    user_id = fields.Many2one('res.users', string='User', required=True, index=True, ondelete='cascade')
    name = fields.Char(string='Label', help='Device or client this token was issued to, e.g. "Parent app - Aarav\'s phone".')
    token_hash = fields.Char(required=True, index=True, copy=False)
    token_last4 = fields.Char(string='Last 4', readonly=True, copy=False)
    expires_at = fields.Datetime(string='Expires At')
    last_used_at = fields.Datetime(string='Last Used At', readonly=True, copy=False)
    active = fields.Boolean(default=True, help='Unchecked = revoked.')
    auth_method = fields.Selection(
        [('password', 'Password'), ('otp', 'OTP')], string='Login Method',
        default='password', required=True, readonly=True,
        help='How this session was opened. Modules that add a login method extend the list.')
    step_up_required = fields.Boolean(
        string='Needs Confirmation', readonly=True, copy=False,
        help='Opened by a weaker login method (e.g. face): sensitive actions ask for '
             'the password or an OTP first.')
    verified_until = fields.Datetime(
        string='Confirmed Until', readonly=True, copy=False,
        help='Until when this session counts as having recently confirmed its password or OTP.')

    _token_hash_unique = models.Constraint('unique(token_hash)', 'This token already exists.')

    @staticmethod
    def _hash(raw_token):
        return hashlib.sha256(raw_token.encode()).hexdigest()

    @api.model
    def _issue_for_user(self, user, name=False, ttl_days=30, auth_method='password',
                        step_up_required=False, ttl_minutes=None):
        """Create a new token for `user` and return the raw token string.
        The raw value is never stored - only its hash - so this is the one
        and only place it is available.

        `ttl_minutes`, when given, overrides `ttl_days` (short kiosk
        sessions). A session opened with a password or OTP starts out as
        recently confirmed; one with `step_up_required` does not.
        """
        raw_token = 'orb_' + secrets.token_urlsafe(32)
        now = fields.Datetime.now()
        vals = {
            'user_id': user.id,
            'name': name or False,
            'token_hash': self._hash(raw_token),
            'token_last4': raw_token[-4:],
            'auth_method': auth_method,
            'step_up_required': step_up_required,
            'verified_until': False if step_up_required else now + timedelta(minutes=STEP_UP_MINUTES),
        }
        if ttl_minutes:
            vals['expires_at'] = now + timedelta(minutes=ttl_minutes)
        elif ttl_days:
            vals['expires_at'] = now + timedelta(days=ttl_days)
        self.sudo().create(vals)
        return raw_token

    @api.model
    def _verify_token(self, raw_token):
        """Return the res.users record the token resolves to, or an empty
        recordset if the token is missing, revoked or expired. Bumps
        last_used_at on success.
        """
        return self._verify_token_record(raw_token).user_id

    @api.model
    def _verify_token_record(self, raw_token):
        """Same check as _verify_token, but returns the token record itself
        (empty if missing, revoked, expired or its user is archived)."""
        if not raw_token:
            return self.browse()
        token = self.sudo().search([
            ('token_hash', '=', self._hash(raw_token)),
            ('active', '=', True),
        ], limit=1)
        if not token or not token.user_id.active:
            return self.browse()
        if token.expires_at and token.expires_at < fields.Datetime.now():
            return self.browse()
        token.write({'last_used_at': fields.Datetime.now()})
        return token

    @api.model
    def _revoke_all_for_user(self, user, keep=None):
        """Revoke every active token of `user` except `keep` - used after a
        password change/reset so a stolen token stops working."""
        domain = [('user_id', '=', user.id), ('active', '=', True)]
        if keep:
            domain.append(('id', 'not in', keep.ids))
        self.sudo().search(domain).action_revoke()

    def _mark_verified(self):
        """The user just confirmed their password or OTP on this session."""
        self.sudo().write({'verified_until': fields.Datetime.now() + timedelta(minutes=STEP_UP_MINUTES)})

    def _is_recently_verified(self):
        self.ensure_one()
        return bool(self.verified_until and self.verified_until >= fields.Datetime.now())

    def action_revoke(self):
        self.write({'active': False})
