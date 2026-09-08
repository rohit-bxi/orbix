# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import api, models


class OpAdmission(models.Model):
    _inherit = 'op.admission'

    @api.onchange('fees_term_id')
    def _onchange_fees_term_id_bxi_fee_management(self):
        if self.fees_term_id and self.fees_term_id.total_amount and not self.fees:
            self.fees = self.fees_term_id.total_amount
