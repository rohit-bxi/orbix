# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, models


class BxiApiToken(models.Model):
    _inherit = 'bxi.api.token'

    # Uninstalling face login ends every session it opened.
    auth_method = fields.Selection(
        selection_add=[('face', 'Face'), ('face_kiosk', 'Face (kiosk)')],
        ondelete={'face': 'cascade', 'face_kiosk': 'cascade'})
    face_kiosk_id = fields.Many2one(
        'bxi.face.kiosk', string='Kiosk', readonly=True, index=True, ondelete='set null',
        help='Kiosk this session was opened on; revoking the kiosk ends it.')
