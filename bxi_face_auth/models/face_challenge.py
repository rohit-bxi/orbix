# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

import hashlib
import random
import secrets
from datetime import timedelta

from odoo import api, fields, models

CHALLENGE_TTL_SECONDS = 60
SELECTION_TTL_SECONDS = 120


def _hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class BxiFaceChallenge(models.Model):
    """A one-time head-turn challenge for face login: the app must send
    one photo per action within CHALLENGE_TTL_SECONDS. The random order
    means a recording made for an earlier challenge doesn't fit the next.

    When one face matches several accounts of the same person, the same
    record carries the short-lived selection token for
    /api/v1/auth/face-login/select."""
    _name = 'bxi.face.challenge'
    _description = 'Face Login Challenge'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Challenge ID', required=True, index=True, copy=False)
    actions = fields.Char(required=True)
    expires_at = fields.Datetime(required=True)
    used_at = fields.Datetime()
    ip = fields.Char()
    selection_hash = fields.Char(index=True, copy=False)
    selection_user_ids = fields.Many2many('res.users', 'bxi_face_challenge_selection_rel', 'challenge_id', 'user_id')
    selection_expires_at = fields.Datetime()
    selection_used_at = fields.Datetime()
    selection_kiosk_id = fields.Many2one('bxi.face.kiosk', ondelete='set null')
    selection_device_name = fields.Char()

    _name_unique = models.Constraint('unique(name)', 'Challenge IDs are unique.')

    @api.model
    def _create_challenge(self, ip=None):
        turns = ['left', 'right']
        random.SystemRandom().shuffle(turns)
        return self.sudo().create({
            'name': 'fc_' + secrets.token_urlsafe(18),
            'actions': ','.join(['center'] + turns),
            'expires_at': fields.Datetime.now() + timedelta(seconds=CHALLENGE_TTL_SECONDS),
            'ip': ip or False,
        })

    @api.model
    def _consume(self, challenge_id):
        """The challenge, marked used, or an empty recordset if it is
        unknown, already used or expired. One attempt per challenge."""
        challenge = self.sudo().search([('name', '=', challenge_id)], limit=1) \
            if isinstance(challenge_id, str) and challenge_id else self.browse()
        if not challenge or challenge.used_at or challenge.expires_at < fields.Datetime.now():
            return self.browse()
        challenge.used_at = fields.Datetime.now()
        return challenge

    def _get_actions(self):
        self.ensure_one()
        return self.actions.split(',')

    def _start_selection(self, users, kiosk=None, device_name=None):
        self.ensure_one()
        raw = 'fs_' + secrets.token_urlsafe(24)
        self.sudo().write({
            'selection_hash': _hash(raw),
            'selection_user_ids': [(6, 0, users.ids)],
            'selection_expires_at': fields.Datetime.now() + timedelta(seconds=SELECTION_TTL_SECONDS),
            'selection_kiosk_id': kiosk.id if kiosk else False,
            'selection_device_name': device_name or False,
        })
        return raw

    @api.model
    def _find_selection(self, raw):
        """The challenge holding a still-valid selection token, or empty."""
        challenge = self.sudo().search([('selection_hash', '=', _hash(raw))], limit=1) \
            if isinstance(raw, str) and raw else self.browse()
        if (not challenge or challenge.selection_used_at
                or challenge.selection_expires_at < fields.Datetime.now()):
            return self.browse()
        return challenge

    def _mark_selection_used(self):
        self.sudo().write({'selection_used_at': fields.Datetime.now()})
