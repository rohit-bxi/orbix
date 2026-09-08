# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, models


class OpCertificate(models.Model):
    _inherit = 'op.certificate'

    event_registration_id = fields.Many2one('event.registration', readonly=True, copy=False)
