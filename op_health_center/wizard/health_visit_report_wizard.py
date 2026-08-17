from odoo import fields, models


class HealthVisitReportWizard(models.TransientModel):
    _name = 'op.health.visit.report.wizard'
    _description = 'Health Visit History Report'

    date_from = fields.Date(string='Date From', required=True)
    date_to = fields.Date(string='Date To', required=True)
    patient_type = fields.Selection([
        ('all', 'All'),
        ('student', 'Students Only'),
        ('faculty', 'Teachers Only'),
    ], default='all', required=True)

    def visit_report(self):
        domain = [
            ('visit_datetime', '>=', self.date_from),
            ('visit_datetime', '<=', self.date_to),
        ]
        if self.patient_type != 'all':
            domain.append(('patient_type', '=', self.patient_type))
        visits = self.env['op.health.visit'].search(domain, order='visit_datetime')

        all_data = [{
            'patient_name': visit.patient_name,
            'patient_type': dict(visit._fields['patient_type'].selection).get(visit.patient_type),
            'visit_datetime': visit.visit_datetime.strftime('%m/%d/%Y %I:%M %p'),
            'visit_type': dict(visit._fields['visit_type'].selection).get(visit.visit_type),
            'attended_by': visit.attended_by.name or '',
            'diagnosis': visit.diagnosis or '',
            'state': dict(visit._fields['state'].selection).get(visit.state),
        } for visit in visits]

        datas = {
            'all_data': all_data,
            'from_date': self.date_from,
            'to_date': self.date_to,
        }
        return self.env.ref('op_health_center.action_report_health_visit').report_action(self, data=datas)
