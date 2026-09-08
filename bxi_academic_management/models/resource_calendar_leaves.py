# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, models


class ResourceCalendarLeaves(models.Model):
    _inherit = ['resource.calendar.leaves', 'mail.thread']
    _name = 'resource.calendar.leaves'

    name = fields.Char(required=True)
    description = fields.Text('Description', tracking=True)
