# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, models


class OpParent(models.Model):
    _name = 'op.parent'
    _inherit = ['op.parent', 'bxi.identity.verification.mixin']

    id_document_ids = fields.Many2many(
        'ir.attachment', 'op_parent_id_document_rel', 'parent_id', 'attachment_id', string='ID Documents',
        help='Scanned ID proof (image or PDF) sent for verification.')
