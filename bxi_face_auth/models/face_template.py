# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

import base64

from odoo import api, fields, models

from ..lib.engine import embedding_from_bytes, embedding_to_bytes


class BxiFaceTemplate(models.Model):
    """One enrolment photo: its face embedding and a downscaled copy of the
    photo for staff review, both encrypted (see bxi.face.service._fernet).
    Kept apart from the profile picture (image_1920), which users can
    change themselves through /api/v1/me/avatar."""
    _name = 'bxi.face.template'
    _description = 'Face Login Photo'
    _order = 'enrolment_id, sequence, id'

    enrolment_id = fields.Many2one('bxi.face.enrolment', required=True, index=True, ondelete='cascade')
    user_id = fields.Many2one(related='enrolment_id.user_id', store=True, index=True)
    company_id = fields.Many2one(related='enrolment_id.company_id', store=True, index=True)
    sequence = fields.Integer()
    action = fields.Char(help='Pose asked for when the photo was taken (center/left/right), if any.')
    embedding_enc = fields.Text(string='Encrypted Embedding', required=True, groups='base.group_system')
    image_enc = fields.Binary(string='Encrypted Photo', attachment=True, groups='base.group_system')
    yaw = fields.Float(digits=(4, 3))
    det_score = fields.Float(string='Detection Score', digits=(4, 3))
    face_pixels = fields.Integer()
    sharpness = fields.Float(digits=(8, 1))

    @api.model
    def _create_from_analysis(self, enrolment, analysis, sequence=0, action=None):
        Service = self.env['bxi.face.service']
        return self.sudo().create({
            'enrolment_id': enrolment.id,
            'sequence': sequence,
            'action': action or False,
            'embedding_enc': Service._encrypt(embedding_to_bytes(analysis.embedding)).decode(),
            'image_enc': base64.b64encode(Service._encrypt(analysis.jpeg)),
            'yaw': analysis.yaw,
            'det_score': analysis.det_score,
            'face_pixels': analysis.face_pixels,
            'sharpness': analysis.sharpness,
        })

    def _get_embedding(self):
        self.ensure_one()
        raw = self.env['bxi.face.service']._decrypt(self.sudo().embedding_enc)
        return embedding_from_bytes(raw) if raw else None

    def _get_image(self):
        """The review photo as JPEG bytes, or None."""
        self.ensure_one()
        stored = self.sudo().with_context(bin_size=False).image_enc
        if not stored:
            return None
        return self.env['bxi.face.service']._decrypt(base64.b64decode(stored))
