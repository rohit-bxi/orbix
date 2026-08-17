from odoo import api, models


class VisitorReport(models.AbstractModel):
    _name = 'report.visit_data.dailyvisitor'
    _description = 'Get hash integrity result as PDF.'

    @api.model
    def _get_report_values(self, docids, data=None):
        print("entered report successfully")
        return {}
