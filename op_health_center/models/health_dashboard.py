from dateutil.relativedelta import relativedelta

from odoo import fields, models, api, _


class HealthDashboard(models.TransientModel):
    _name = 'op.health.dashboard'
    _description = 'Health Center Dashboard'
    _rec_name = 'name'

    name = fields.Char(default=lambda self: _('Health Center Dashboard'))

    # KPIs
    visit_count_today = fields.Integer(string='Visits Today', readonly=True)
    visit_count_month = fields.Integer(string='Visits This Month', readonly=True)
    open_case_count = fields.Integer(string='Open Cases', readonly=True)
    upcoming_vaccination_count = fields.Integer(string='Vaccinations Due (30 days)', readonly=True)
    active_alert_count = fields.Integer(string='Active Medical Alerts', readonly=True)
    checkup_compliance_rate = fields.Float(string='Checkup Compliance %', readonly=True)

    # Activity feeds
    recent_visit_ids = fields.Many2many(
        'op.health.visit', string='Recent Visits', compute='_compute_recent_visits')
    upcoming_vaccination_ids = fields.Many2many(
        'op.health.vaccination', string='Upcoming Vaccinations', compute='_compute_upcoming_vaccinations')
    alert_student_ids = fields.Many2many(
        'op.student', string='Students Requiring Attention', compute='_compute_alerts')
    alert_faculty_ids = fields.Many2many(
        'op.faculty', string='Teachers Requiring Attention', compute='_compute_alerts')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)

        res['visit_count_today'] = self.env['op.health.visit'].search_count(
            [('visit_datetime', '>=', today.strftime('%Y-%m-%d 00:00:00'))])
        res['visit_count_month'] = self.env['op.health.visit'].search_count(
            [('visit_datetime', '>=', month_start.strftime('%Y-%m-%d'))])
        res['open_case_count'] = self.env['op.health.visit'].search_count(
            [('state', 'in', ('confirmed', 'under_treatment', 'referred'))])

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

    def _compute_recent_visits(self):
        visits = self.env['op.health.visit'].search([], order='visit_datetime desc', limit=8)
        for record in self:
            record.recent_visit_ids = visits

    def _compute_upcoming_vaccinations(self):
        today = fields.Date.context_today(self)
        due_before = fields.Date.to_string(today + relativedelta(days=30))
        vaccinations = self.env['op.health.vaccination'].search([
            ('state', '=', 'scheduled'),
            ('next_due_date', '>=', today.strftime('%Y-%m-%d')),
            ('next_due_date', '<=', due_before),
        ], order='next_due_date asc', limit=8)
        for record in self:
            record.upcoming_vaccination_ids = vaccinations

    def _compute_alerts(self):
        students = self.env['op.student'].search([('medical_alert', '=', True)], limit=6)
        faculty = self.env['op.faculty'].search([('medical_alert', '=', True)], limit=6)
        for record in self:
            record.alert_student_ids = students
            record.alert_faculty_ids = faculty

    def action_view_visit_report(self):
        return self.env['ir.actions.act_window']._for_xml_id('op_health_center.action_health_visit_report')

    def action_view_open_cases(self):
        action = self.env['ir.actions.act_window']._for_xml_id('op_health_center.action_health_visit')
        action['domain'] = [('state', 'in', ('confirmed', 'under_treatment', 'referred'))]
        action['context'] = {}
        return action

    def action_view_vaccination_report(self):
        return self.env['ir.actions.act_window']._for_xml_id('op_health_center.action_health_vaccination_report')

    def action_view_checkup_report(self):
        return self.env['ir.actions.act_window']._for_xml_id('op_health_center.action_health_checkup_report')

    def action_view_alert_students(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Students Requiring Attention'),
            'res_model': 'op.student',
            'view_mode': 'list,form',
            'domain': [('medical_alert', '=', True)],
        }

    def action_view_alert_faculty(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Teachers Requiring Attention'),
            'res_model': 'op.faculty',
            'view_mode': 'list,form',
            'domain': [('medical_alert', '=', True)],
        }
