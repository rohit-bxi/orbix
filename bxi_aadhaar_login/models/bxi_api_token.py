# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import api, fields, models


class BxiApiToken(models.Model):
    _inherit = 'bxi.api.token'

    login_identifier = fields.Selection(
        [('aadhaar', 'Aadhaar Number')], string='Signed In With', readonly=True, copy=False,
        help='Set when the session was opened by typing an Aadhaar number instead of the username.')

    @api.model
    def _issue_for_user(self, user, *args, **kwargs):
        """Context key `bxi_login_identifier` (set by the Aadhaar login
        routes) is recorded on the new session for the audit trail."""
        raw_token = super()._issue_for_user(user, *args, **kwargs)
        identifier = self.env.context.get('bxi_login_identifier')
        if identifier:
            self.sudo().search([('token_hash', '=', self._hash(raw_token))], limit=1).login_identifier = identifier
        return raw_token
