# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Smart Books: library books (op.media) mapped to a curriculum.

The Add Smart Book screen asks only for Book Title, Subject, Class and
Curriculum, so authors, publishers and a genre - which the library needs
for its own catalogue - are required only for books without a
curriculum."""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OpMediaCurriculum(models.Model):
    _inherit = 'op.media'

    curriculum_id = fields.Many2one('bxi.curriculum', string='Curriculum', index=True)
    author_ids = fields.Many2many(required=False)
    publisher_ids = fields.Many2many(required=False)
    genre_id = fields.Many2one(required=False)
    bxi_locked = fields.Boolean(
        string='Locked', copy=False, tracking=True,
        help='A locked Smart Book cannot be edited or deleted until it is unlocked.')

    @api.constrains('name', 'curriculum_id', 'author_ids', 'publisher_ids', 'genre_id')
    def _check_bxi_library_details(self):
        for media in self:
            if media.curriculum_id:
                continue
            if not media.author_ids:
                raise ValidationError(_('Add at least one author to %s.', media.name))
            if not media.publisher_ids:
                raise ValidationError(_('Add at least one publisher to %s.', media.name))
            if not media.genre_id:
                raise ValidationError(_('Set the genre of %s.', media.name))

    def action_bxi_toggle_lock(self):
        for media in self:
            media.bxi_locked = not media.bxi_locked
