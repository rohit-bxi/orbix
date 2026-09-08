# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, models


class OpMediaCurriculum(models.Model):
    _inherit = 'op.media'

    curriculum_id = fields.Many2one('bxi.curriculum', string='Curriculum')
