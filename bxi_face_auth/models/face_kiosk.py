# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

import hashlib
import secrets

from odoo import api, fields, models


class BxiFaceKiosk(models.Model):
    """A shared school device (library or lab tablet) allowed to log people
    in by face alone, searching everyone enrolled at its school. It sends
    its key in the X-Kiosk-Key header; only the key's hash is stored."""
    _name = 'bxi.face.kiosk'
    _description = 'Face Login Kiosk'
    _order = 'name'

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    key_hash = fields.Char(required=True, index=True, copy=False, groups='base.group_system')
    key_last4 = fields.Char(readonly=True, copy=False)
    allow_student = fields.Boolean(default=True)
    allow_teacher = fields.Boolean(default=True)
    allow_parent = fields.Boolean(default=False)
    allow_staff = fields.Boolean(default=False)
    session_minutes = fields.Integer(default=15, help='How long a session opened on this kiosk lasts.')
    active = fields.Boolean(default=True)
    last_used_at = fields.Datetime(readonly=True)
    created_by_id = fields.Many2one('res.users', readonly=True)

    @staticmethod
    def _hash(raw):
        return hashlib.sha256(raw.encode()).hexdigest()

    @api.model
    def _create_with_key(self, vals):
        """Create a kiosk and return (kiosk, raw_key). The raw key is only
        ever available here."""
        raw = 'kiosk_' + secrets.token_urlsafe(32)
        kiosk = self.sudo().create(dict(vals, key_hash=self._hash(raw), key_last4=raw[-4:]))
        return kiosk, raw

    @api.model
    def _from_key(self, raw):
        if not raw:
            return self.browse()
        kiosk = self.sudo().search([('key_hash', '=', self._hash(raw)), ('active', '=', True)], limit=1)
        if kiosk:
            kiosk.last_used_at = fields.Datetime.now()
        return kiosk

    def _allowed_roles(self):
        self.ensure_one()
        return [role for role in ('student', 'teacher', 'parent', 'staff') if self['allow_%s' % role]]
