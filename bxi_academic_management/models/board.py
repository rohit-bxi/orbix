# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, models


class BxiBoard(models.Model):
    _name = 'bxi.board'
    _description = 'Education Board'
    _order = 'name'

    name = fields.Char('Name', required=True)
    active = fields.Boolean(default=True)

    _unique_name = models.Constraint(
        'unique(name)',
        'A board with this name already exists.',
    )
