# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, models


class BxiStaffResponsibility(models.Model):
    """Extra duties a teacher holds besides teaching, e.g. Exam Coordinator,
    Sports In-charge, House Master."""
    _name = 'bxi.staff.responsibility'
    _description = 'Staff Responsibility'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)

    _unique_name = models.Constraint('unique(name)', 'This responsibility already exists.')
