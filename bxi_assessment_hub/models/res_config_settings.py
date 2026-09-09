# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    bxi_ai_api_key = fields.Char(
        string='AI API Key', config_parameter='bxi_assessment_hub.anthropic_api_key')
    bxi_ai_model = fields.Char(
        string='AI Model', config_parameter='bxi_assessment_hub.anthropic_model',
        help='OpenRouter model id used for AI question generation and auto-grading, '
             'e.g. anthropic/claude-sonnet-5.')
