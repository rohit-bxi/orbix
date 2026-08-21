from odoo import api, models


class OpAdmission(models.Model):
    _inherit = 'op.admission'

    @api.onchange('fees_term_id')
    def _onchange_fees_term_id_bxi_fee_management(self):
        if self.fees_term_id and self.fees_term_id.total_amount and not self.fees:
            self.fees = self.fees_term_id.total_amount
