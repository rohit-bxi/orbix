# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Where a reader is inside a lesson (the Smart Book reader's "Page 1 of
45 - 35%"), kept on website_slides' own per-user lesson progress."""
from odoo import fields, models


class SlideSlidePartner(models.Model):
    _inherit = 'slide.slide.partner'

    bxi_page = fields.Integer('Reading Page', default=0)
    bxi_total_pages = fields.Integer('Reading Pages', default=0)
    bxi_percent = fields.Float('Reading Progress (%)', default=0.0)
    bxi_position_date = fields.Datetime('Last Read')
