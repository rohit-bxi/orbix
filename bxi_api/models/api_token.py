# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

import hashlib
import secrets
from datetime import timedelta

from odoo import api, fields, models


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

    _sql_constraints = [
        ('token_hash_unique', 'unique(token_hash)', 'This token already exists.'),
    ]

    @staticmethod
    def _hash(raw_token):
        return hashlib.sha256(raw_token.encode()).hexdigest()

    @api.model
    def _issue_for_user(self, user, name=False, ttl_days=30):
        """Create a new token for `user` and return the raw token string.
        The raw value is never stored - only its hash - so this is the one
        and only place it is available.
        """
        raw_token = 'orb_' + secrets.token_urlsafe(32)
        vals = {
            'user_id': user.id,
            'name': name or False,
            'token_hash': self._hash(raw_token),
            'token_last4': raw_token[-4:],
        }
        if ttl_days:
            vals['expires_at'] = fields.Datetime.now() + timedelta(days=ttl_days)
        self.sudo().create(vals)
        return raw_token

    @api.model
    def _verify_token(self, raw_token):
        """Return the res.users record the token resolves to, or an empty
        recordset if the token is missing, revoked or expired. Bumps
        last_used_at on success.
        """
        if not raw_token:
            return self.env['res.users']
        token = self.sudo().search([
            ('token_hash', '=', self._hash(raw_token)),
            ('active', '=', True),
        ], limit=1)
        if not token:
            return self.env['res.users']
        if token.expires_at and token.expires_at < fields.Datetime.now():
            return self.env['res.users']
        token.write({'last_used_at': fields.Datetime.now()})
        return token.user_id

    def action_revoke(self):
        self.write({'active': False})
