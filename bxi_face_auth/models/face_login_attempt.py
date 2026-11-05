# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, models

ATTEMPT_RESULTS = [
    ('success', 'Logged in'),
    ('identified', 'Identified (no login)'),
    ('selection_required', 'Account choice offered'),
    ('face_not_recognised', 'Not recognised'),
    ('ambiguous', 'Ambiguous'),
    ('liveness_failed', 'Liveness failed'),
    ('locked', 'Locked'),
    ('no_face', 'No face'),
    ('multiple_faces', 'Several faces'),
    ('poor_quality', 'Poor quality'),
    ('invalid_image', 'Invalid image'),
    ('face_engine_unavailable', 'Engine unavailable'),
]


class BxiFaceLoginAttempt(models.Model):
    """Audit log of face-login attempts, also used for the lockout and for
    tuning the thresholds (scores are kept, photos are not)."""
    _name = 'bxi.face.login.attempt'
    _description = 'Face Login Attempt'
    _order = 'create_date desc, id desc'

    mode = fields.Selection([
        ('phone', 'Own device'),
        ('auto', 'Face only'),
        ('kiosk', 'Kiosk'),
        ('identify', 'Identify only'),
    ], required=True)
    company_id = fields.Many2one('res.company', index=True)
    kiosk_id = fields.Many2one('bxi.face.kiosk', ondelete='set null')
    ip = fields.Char()
    device_name = fields.Char()
    login_hint = fields.Char()
    target_user_ids = fields.Many2many(
        'res.users', 'bxi_face_attempt_target_rel', 'attempt_id', 'user_id',
        string='Accounts Tried', help='Accounts the login hint pointed to (own-device mode).')
    user_id = fields.Many2one('res.users', string='Logged In As', index=True, ondelete='set null')
    result = fields.Selection(ATTEMPT_RESULTS, index=True)
    reason = fields.Char(help='Detail, e.g. which liveness rule failed.')
    best_score = fields.Float(digits=(4, 3))
    second_score = fields.Float(digits=(4, 3))
    live_score = fields.Float(digits=(4, 3))
