from odoo import fields, models


class VisitorReport(models.TransientModel):
    _name = 'visitor.report.wizard'

    date_from = fields.Date(string="Date From")
    date_to = fields.Date(string="Date To")

    def visitor_report(self):
        check_in_data = self.env['visit.data'].search([('check_in_date', '>=', self.date_from),
                                                       ('check_in_date', '<=', self.date_to)])
        name_list = []
        for data in check_in_data:
            data = {
                'name': data.v_name.v_name,
                'mobile': data.v_phn,
                'entry_date': data.check_in_date.strftime('%m/%d/%Y %I:%M:%S %p'),
                'refer_person': data.employee_id.name,
                'reason': data.v_purpose,
            }
            name_list.append(data)
        datas = {
            'all_data': name_list,
            'from_date': self.date_from,
            'to_date': self.date_to
        }
        print("data", datas)
        return self.env.ref('visitor_management.visitor_report_action').report_action(self, data=datas)
