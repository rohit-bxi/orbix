# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, models


class OpStudent(models.Model):
    _name = 'op.student'
    _inherit = ['op.student', 'bxi.identity.verification.mixin']

    id_document_ids = fields.Many2many(
        'ir.attachment', 'op_student_id_document_rel', 'student_id', 'attachment_id', string='ID Documents',
        help='Scanned ID proof (image or PDF) sent for verification.')
