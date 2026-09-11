# -*- coding: utf-8 -*-
from collections import Counter

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

MONTH_WINDOW = 6
VISIT_LIST_LIMIT = 10
TOP_HOSTS_LIMIT = 5
RECENT_ACTIVITY_LIMIT = 8
OVERSTAY_HOURS = 8

VISIT_STATUS_KIND = {
    'draft': 'info',
    'checkin': 'warning',
    'checkout': 'success',
}

TYPE_LABELS = {
    'buyer': 'Buyer',
    'guest': 'Guest',
    'supplier': 'Supplier',
    'delivery': 'Delivery',
}


class BxiVisitorDashboard(models.AbstractModel):
    """Server-side aggregation for the Visitor Management Dashboard client
    action. Every number here is a live query against visit.data /
    visitor.data - nothing is cached, so the dashboard always matches the
    underlying list views.
    """
    _name = 'bxi.visitor.dashboard'
    _description = 'Visitor Management Dashboard'

    def _month_bounds(self, months_ago=0):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1) - relativedelta(months=months_ago)
        month_end = month_start + relativedelta(months=1) - relativedelta(days=1)
        return month_start, month_end

    @api.model
    def get_dashboard_data(self):
        Visit = self.env['visit.data'].sudo()
        visits = Visit.search([])
        return {
            'kpis': self._get_kpis(visits),
            'visit_list': self._get_visit_list(Visit),
            'charts': {
                'status_distribution': self._get_status_distribution(visits),
                'type_distribution': self._get_type_distribution(visits),
                'department_wise': self._get_department_wise(visits),
                'monthly_visit_trend': self._get_monthly_visit_trend(visits),
            },
            'top_hosts': self._get_top_hosts(visits),
            'stats': self._get_secondary_stats(visits),
            'recent_activity': self._get_recent_activity(Visit),
        }

    def _get_kpis(self, visits):
        today = fields.Date.context_today(self)
        tomorrow = today + relativedelta(days=1)
        visits_today = visits.filtered(
            lambda v: v.check_in_date and today <= v.check_in_date.date() < tomorrow)
        currently_checked_in = visits.filtered(lambda v: v.state == 'checkin')
        checked_out_today = visits.filtered(
            lambda v: v.state == 'checkout' and v.check_out_date
            and today <= v.check_out_date.date() < tomorrow)
        return {
            'visits_today': {'value': len(visits_today)},
            'currently_checked_in': {'value': len(currently_checked_in)},
            'checked_out_today': {'value': len(checked_out_today)},
            'checkout_rate': {
                'value': round(len(checked_out_today) / len(visits_today) * 100.0, 1)
                if visits_today else 0.0,
            },
        }

    def _get_visit_list(self, Visit):
        records = Visit.search([], order='write_date desc', limit=VISIT_LIST_LIMIT)
        return [{
            'id': v.id,
            'visitor_name': v.v_name.v_name or '',
            'company': v.v_company or '',
            'host': v.employee_id.name or '',
            'check_in_date': fields.Datetime.to_string(v.check_in_date) if v.check_in_date else '',
            'state': v.state,
        } for v in records]

    def _get_status_distribution(self, visits):
        status_labels = dict(visits._fields['state'].selection)
        counter = Counter(visits.mapped('state'))
        ordered = [key for key, _label in visits._fields['state'].selection if key in counter]
        return {
            'labels': [status_labels.get(k, k) for k in ordered],
            'values': [counter[k] for k in ordered],
        }

    def _get_type_distribution(self, visits):
        counter = Counter(visits.mapped('I_AM'))
        ordered = sorted(counter, key=lambda k: counter[k], reverse=True)
        return {
            'labels': [TYPE_LABELS.get(k, k) for k in ordered],
            'values': [counter[k] for k in ordered],
        }

    def _get_department_wise(self, visits):
        counter = Counter(v.dept.name for v in visits if v.dept)
        ordered = sorted(counter, key=lambda k: counter[k], reverse=True)
        return {
            'labels': ordered,
            'values': [counter[k] for k in ordered],
        }

    def _get_monthly_visit_trend(self, visits):
        labels, values = [], []
        for i in range(MONTH_WINDOW - 1, -1, -1):
            month_start, month_end = self._month_bounds(i)
            month_records = visits.filtered(
                lambda v: v.check_in_date and month_start <= v.check_in_date.date() <= month_end)
            labels.append(month_start.strftime('%b'))
            values.append(len(month_records))
        return {'labels': labels, 'values': values}

    def _get_top_hosts(self, visits):
        counter = Counter()
        dept_by_employee = {}
        for visit in visits:
            if not visit.employee_id:
                continue
            counter[visit.employee_id.id] += 1
            dept_by_employee[visit.employee_id.id] = (visit.employee_id.name, visit.dept.name or '-')
        ordered = sorted(counter, key=lambda k: counter[k], reverse=True)[:TOP_HOSTS_LIMIT]
        return [{
            'name': dept_by_employee[emp_id][0],
            'department': dept_by_employee[emp_id][1],
            'visit_count': counter[emp_id],
        } for emp_id in ordered]

    def _get_secondary_stats(self, visits):
        today = fields.Date.context_today(self)
        checked_out = visits.filtered(lambda v: v.state == 'checkout' and v.check_in_date and v.check_out_date)
        if checked_out:
            durations = [
                (v.check_out_date - v.check_in_date).total_seconds() / 60.0 for v in checked_out]
            avg_duration = round(sum(durations) / len(durations), 1)
        else:
            avg_duration = 0.0

        visitor_counter = Counter(visits.mapped('v_name').ids)
        repeat_visitors = len([vid for vid, count in visitor_counter.items() if count > 1])

        cutoff = fields.Datetime.now() - relativedelta(hours=OVERSTAY_HOURS)
        overstayed = visits.filtered(
            lambda v: v.state == 'checkin' and v.check_in_date and v.check_in_date < cutoff)

        return {
            'avg_visit_duration_minutes': avg_duration,
            'repeat_visitors': repeat_visitors,
            'overstayed_visitors': len(overstayed),
        }

    def _get_recent_activity(self, Visit):
        activities = []
        visit_labels = dict(Visit._fields['state'].selection)
        for visit in Visit.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': '%s (%s) - %s' % (
                    visit.v_name.v_name or 'Visitor', visit.v_company or '',
                    visit_labels.get(visit.state, visit.state)),
                'date': fields.Datetime.to_string(visit.write_date),
                'kind': VISIT_STATUS_KIND.get(visit.state, 'info'),
            })
        activities.sort(key=lambda a: a['date'], reverse=True)
        return activities[:RECENT_ACTIVITY_LIMIT]
