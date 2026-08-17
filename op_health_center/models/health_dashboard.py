from dateutil.relativedelta import relativedelta

from odoo import fields, models, api, _


class HealthDashboard(models.TransientModel):
    _name = 'op.health.dashboard'
    _description = 'Health Center Dashboard'
    _rec_name = 'name'

    name = fields.Char(default=lambda self: _('Health Center Dashboard'))
    visit_count_month = fields.Integer(string='Visits This Month', readonly=True)
    upcoming_vaccination_count = fields.Integer(string='Vaccinations Due (30 days)', readonly=True)
    active_alert_count = fields.Integer(string='Active Medical Alerts', readonly=True)
    checkup_compliance_rate = fields.Float(string='Checkup Compliance %', readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)

        res['visit_count_month'] = self.env['op.health.visit'].search_count(
            [('visit_datetime', '>=', month_start.strftime('%Y-%m-%d'))])

        due_before = fields.Date.to_string(today + relativedelta(days=30))
        res['upcoming_vaccination_count'] = self.env['op.health.vaccination'].search_count([
            ('state', '=', 'scheduled'),
            ('next_due_date', '>=', today.strftime('%Y-%m-%d')),
            ('next_due_date', '<=', due_before),
        ])

        student_alerts = self.env['op.student'].search_count([('medical_alert', '=', True)])
        faculty_alerts = self.env['op.faculty'].search_count([('medical_alert', '=', True)])
        res['active_alert_count'] = student_alerts + faculty_alerts

        total_students = self.env['op.student'].search_count([])
        checked_students = self.env['op.student'].search_count([('last_checkup_date', '!=', False)])
        res['checkup_compliance_rate'] = (checked_students / total_students * 100.0) if total_students else 0.0

        return res

    def action_view_visit_report(self):
        return self.env['ir.actions.act_window']._for_xml_id('op_health_center.action_health_visit_report')

    def action_view_vaccination_report(self):
        return self.env['ir.actions.act_window']._for_xml_id('op_health_center.action_health_vaccination_report')

    def action_view_checkup_report(self):
        return self.env['ir.actions.act_window']._for_xml_id('op_health_center.action_health_checkup_report')
