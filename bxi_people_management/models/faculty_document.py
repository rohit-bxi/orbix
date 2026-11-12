# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64

from odoo import api, fields, models
from odoo.tools.mimetypes import guess_mimetype

DOCUMENT_TYPES = [
    ('aadhaar', 'Aadhaar Card'),
    ('cv', 'CV / Resume'),
    ('certificate', 'Certificate'),
    ('other', 'Other'),
]


class BxiFacultyDocument(models.Model):
    """A teacher's file on record: Aadhaar card, CV, certificates."""
    _name = 'bxi.faculty.document'
    _description = 'Teacher Document'
    _order = 'create_date desc, id desc'

    faculty_id = fields.Many2one('op.faculty', string='Teacher', required=True, index=True, ondelete='cascade')
    doc_type = fields.Selection(DOCUMENT_TYPES, string='Type', required=True, default='other')
    name = fields.Char(string='Title', required=True)
    file = fields.Binary(string='File', attachment=True, required=True)
    filename = fields.Char()
    mimetype = fields.Char(compute='_compute_file_info', store=True)
    file_size = fields.Integer(compute='_compute_file_info', store=True)

    @api.depends('file')
    def _compute_file_info(self):
        for document in self.with_context(bin_size=False):
            content = base64.b64decode(document.file) if document.file else b''
            document.mimetype = guess_mimetype(content) if content else False
            document.file_size = len(content)
