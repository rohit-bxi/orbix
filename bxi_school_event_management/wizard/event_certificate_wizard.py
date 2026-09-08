# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, models


class EventCertificateWizard(models.TransientModel):
    _name = 'event.certificate.wizard'
    _description = 'Generate Participation Certificates'

    event_id = fields.Many2one('event.event', required=True)
    certificate_type_id = fields.Many2one(
        'op.certificate.type', required=True,
        domain=[('category', '=', 'participation')])

    def action_generate(self):
        self.ensure_one()
        return self.event_id.action_generate_participation_certificates(self.certificate_type_id.id)
