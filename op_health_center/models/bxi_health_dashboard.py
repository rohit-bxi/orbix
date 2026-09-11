# -*- coding: utf-8 -*-
from collections import Counter

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

MONTH_WINDOW = 6
VISIT_LIST_LIMIT = 10
TOP_VACCINES_LIMIT = 5
RECENT_ACTIVITY_LIMIT = 8

VISIT_STATUS_KIND = {
    'draft': 'info',
    'confirmed': 'warning',
    'under_treatment': 'warning',
    'resolved': 'success',
    'referred': 'info',
    'cancelled': 'danger',
}
VACCINATION_STATUS_KIND = {
    'scheduled': 'warning',
    'completed': 'success',
    'missed': 'danger',
    'cancelled': 'danger',
}
CHECKUP_STATUS_KIND = {
    'scheduled': 'warning',
    'completed': 'success',
    'cancelled': 'danger',
}


class BxiHealthDashboard(models.AbstractModel):
    """Server-side aggregation for the Health Center Dashboard client
    action. Every number here is a live query against op.health.visit /
    op.health.vaccination / op.health.checkup / op.student / op.faculty -
    nothing is cached, so the dashboard always matches the underlying list
    views. Distinct from the op.health.dashboard wizard used under
    Reports > Dashboard, which stays untouched.
    """
    _name = 'bxi.health.dashboard'
    _description = 'Health Center Dashboard'

    def _month_bounds(self, months_ago=0):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1) - relativedelta(months=months_ago)
        month_end = month_start + relativedelta(months=1) - relativedelta(days=1)
        return month_start, month_end

    @api.model
    def get_dashboard_data(self):
        Visit = self.env['op.health.visit'].sudo()
        visits = Visit.search([])
        return {
            'kpis': self._get_kpis(visits),
            'visit_list': self._get_visit_list(Visit),
            'charts': {
                'visit_status_distribution': self._get_visit_status_distribution(visits),
                'vaccination_status': self._get_vaccination_status(),
                'fitness_distribution': self._get_fitness_distribution(),
                'monthly_visit_trend': self._get_monthly_visit_trend(visits),
            },
            'top_vaccines': self._get_top_vaccines(),
            'stats': self._get_secondary_stats(visits),
            'recent_activity': self._get_recent_activity(),
        }

    def _get_kpis(self, visits):
        today = fields.Date.context_today(self)
        tomorrow = today + relativedelta(days=1)
        month_start, _month_end = self._month_bounds(0)
        next_month_start = month_start + relativedelta(months=1)
        visits_today = len(visits.filtered(
            lambda v: v.visit_datetime and today <= v.visit_datetime.date() < tomorrow))
        visits_month = len(visits.filtered(
            lambda v: v.visit_datetime and month_start <= v.visit_datetime.date() < next_month_start))
        open_cases = len(visits.filtered(lambda v: v.state in ('confirmed', 'under_treatment', 'referred')))

        Student = self.env['op.student'].sudo()
        Faculty = self.env['op.faculty'].sudo()
        total_patients = Student.search_count([]) + Faculty.search_count([])
        checked_patients = Student.search_count([('last_checkup_date', '!=', False)]) \
            + Faculty.search_count([('last_checkup_date', '!=', False)])

        return {
            'visits_today': {'value': visits_today},
            'visits_month': {'value': visits_month},
            'open_cases': {'value': open_cases},
            'checkup_compliance': {
                'value': round(checked_patients / total_patients * 100.0, 1) if total_patients else 0.0,
            },
        }

    def _get_visit_list(self, Visit):
        records = Visit.search([], order='write_date desc', limit=VISIT_LIST_LIMIT)
        return [{
            'id': v.id,
            'patient_name': v.patient_name,
            'visit_type': dict(v._fields['visit_type'].selection).get(v.visit_type, '') or '-',
            'visit_datetime': fields.Datetime.to_string(v.visit_datetime) if v.visit_datetime else '',
            'state': v.state,
        } for v in records]

    def _get_visit_status_distribution(self, visits):
        status_labels = dict(visits._fields['state'].selection)
        counter = Counter(visits.mapped('state'))
        ordered = [key for key, _label in visits._fields['state'].selection if key in counter]
        return {
            'labels': [status_labels.get(k, k) for k in ordered],
            'values': [counter[k] for k in ordered],
        }

    def _get_vaccination_status(self):
        Vaccination = self.env['op.health.vaccination'].sudo()
        total = Vaccination.search_count([])
        completed = Vaccination.search_count([('state', '=', 'completed')])
        scheduled = Vaccination.search_count([('state', '=', 'scheduled')])
        missed = Vaccination.search_count([('state', '=', 'missed')])
        return {'total': total, 'completed': completed, 'scheduled': scheduled, 'missed': missed}

    def _get_fitness_distribution(self):
        Checkup = self.env['op.health.checkup'].sudo()
        checkups = Checkup.search([('fitness_status', '!=', False)])
        fitness_labels = dict(Checkup._fields['fitness_status'].selection)
        counter = Counter(checkups.mapped('fitness_status'))
        ordered = [key for key, _label in Checkup._fields['fitness_status'].selection if key in counter]
        return {
            'labels': [fitness_labels.get(k, k) for k in ordered],
            'values': [counter[k] for k in ordered],
        }

    def _get_monthly_visit_trend(self, visits):
        labels, values = [], []
        for i in range(MONTH_WINDOW - 1, -1, -1):
            month_start, month_end = self._month_bounds(i)
            month_records = visits.filtered(
                lambda v: v.visit_datetime and month_start <= v.visit_datetime.date() <= month_end)
            labels.append(month_start.strftime('%b'))
            values.append(len(month_records))
        return {'labels': labels, 'values': values}

    def _get_top_vaccines(self):
        Vaccination = self.env['op.health.vaccination'].sudo()
        vaccines = self.env['op.health.vaccine.type'].sudo().search([])
        rows = []
        for vaccine in vaccines:
            administered = Vaccination.search_count([('vaccine_id', '=', vaccine.id), ('state', '=', 'completed')])
            pending = Vaccination.search_count([('vaccine_id', '=', vaccine.id), ('state', '=', 'scheduled')])
            total = administered + pending
            rows.append({
                'name': vaccine.name,
                'administered': administered,
                'pending': pending,
                'completion_rate': round(administered / total * 100.0, 1) if total else 0.0,
            })
        rows.sort(key=lambda r: r['administered'], reverse=True)
        return rows[:TOP_VACCINES_LIMIT]

    def _get_secondary_stats(self, visits):
        Student = self.env['op.student'].sudo()
        Faculty = self.env['op.faculty'].sudo()
        today = fields.Date.context_today(self)
        due_before = today + relativedelta(days=30)
        Vaccination = self.env['op.health.vaccination'].sudo()

        active_alert_count = Student.search_count([('medical_alert', '=', True)]) \
            + Faculty.search_count([('medical_alert', '=', True)])
        upcoming_vaccination_count = Vaccination.search_count([
            ('state', '=', 'scheduled'),
            ('next_due_date', '>=', today),
            ('next_due_date', '<=', due_before),
        ])
        overdue_followups = len(visits.filtered(
            lambda v: v.follow_up_required and v.follow_up_date and v.follow_up_date < today
            and v.state not in ('resolved', 'cancelled')))
        return {
            'active_alert_count': active_alert_count,
            'upcoming_vaccination_count': upcoming_vaccination_count,
            'overdue_followups': overdue_followups,
        }

    def _get_recent_activity(self):
        activities = []

        Visit = self.env['op.health.visit'].sudo()
        visit_labels = dict(Visit._fields['state'].selection)
        for visit in Visit.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': 'Visit %s (%s) - %s' % (
                    visit.name, visit.patient_name, visit_labels.get(visit.state, visit.state)),
                'date': fields.Datetime.to_string(visit.write_date),
                'kind': VISIT_STATUS_KIND.get(visit.state, 'info'),
            })

        Vaccination = self.env['op.health.vaccination'].sudo()
        vaccination_labels = dict(Vaccination._fields['state'].selection)
        for vaccination in Vaccination.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': 'Vaccination %s (%s) - %s' % (
                    vaccination.name, vaccination.patient_name,
                    vaccination_labels.get(vaccination.state, vaccination.state)),
                'date': fields.Datetime.to_string(vaccination.write_date),
                'kind': VACCINATION_STATUS_KIND.get(vaccination.state, 'info'),
            })

        Checkup = self.env['op.health.checkup'].sudo()
        checkup_labels = dict(Checkup._fields['state'].selection)
        for checkup in Checkup.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': 'Checkup %s (%s) - %s' % (
                    checkup.name, checkup.patient_name, checkup_labels.get(checkup.state, checkup.state)),
                'date': fields.Datetime.to_string(checkup.write_date),
                'kind': CHECKUP_STATUS_KIND.get(checkup.state, 'info'),
            })

        activities.sort(key=lambda a: a['date'], reverse=True)
        return activities[:RECENT_ACTIVITY_LIMIT]
