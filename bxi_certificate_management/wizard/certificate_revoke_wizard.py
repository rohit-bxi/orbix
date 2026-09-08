# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, models


class OpCertificateRevokeWizard(models.TransientModel):
    _name = 'op.certificate.revoke.wizard'
    _description = 'Revoke Certificate'

    certificate_id = fields.Many2one('op.certificate', required=True)
    reason = fields.Text(required=True)

    def action_confirm_revoke(self):
        self.ensure_one()
        self.certificate_id.action_revoke(self.reason)
