# -*- coding: utf-8 -*-
from collections import Counter

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

MONTH_WINDOW = 6
SESSION_LIST_LIMIT = 10
EQUIPMENT_ATTENTION_LIMIT = 5
RECENT_ACTIVITY_LIMIT = 8

SESSION_STATUS_KIND = {
    'draft': 'info',
    'confirmed': 'warning',
    'in_progress': 'warning',
    'done': 'success',
    'cancelled': 'danger',
}
ISSUE_STATUS_KIND = {
    'issued': 'warning',
    'partial': 'warning',
    'returned': 'success',
    'damaged': 'danger',
}

LAB_TYPE_LABELS = {
    'computer': 'Computer',
    'chemistry': 'Chemistry',
    'physics': 'Physics',
    'biology': 'Biology',
    'other': 'Other',
}


class LabDashboard(models.AbstractModel):
    """Server-side aggregation for the Lab Management Dashboard client
    action. Every number here is a live query against lab.session /
    lab.attendance / lab.equipment / lab.room - nothing is cached, so the
    dashboard always matches the underlying list views.
    """
    _name = 'lab.dashboard'
    _description = 'Lab Management Dashboard'

    def _month_bounds(self, months_ago=0):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1) - relativedelta(months=months_ago)
        month_end = month_start + relativedelta(months=1) - relativedelta(days=1)
        return month_start, month_end

    @api.model
    def get_dashboard_data(self):
        Session = self.env['lab.session'].sudo()
        sessions = Session.search([])
        return {
            'kpis': self._get_kpis(sessions),
            'session_list': self._get_session_list(Session),
            'charts': {
                'status_distribution': self._get_status_distribution(sessions),
                'lab_type_distribution': self._get_lab_type_distribution(),
                'attendance_distribution': self._get_attendance_distribution(),
                'monthly_session_trend': self._get_monthly_session_trend(sessions),
            },
            'equipment_attention': self._get_equipment_attention(),
            'stats': self._get_secondary_stats(),
            'recent_activity': self._get_recent_activity(),
        }

    def _get_kpis(self, sessions):
        today = fields.Date.context_today(self)
        sessions_today = sessions.filtered(lambda s: s.date == today)
        sessions_in_progress = sessions.filtered(lambda s: s.state in ('confirmed', 'in_progress'))

        Issue = self.env['lab.equipment.issue'].sudo()
        equipment_issued = Issue.search_count([('state', 'in', ('issued', 'partial'))])

        Attendance = self.env['lab.attendance'].sudo()
        total_attendance = Attendance.search_count([])
        present_attendance = Attendance.search_count([('status', '=', 'present')])

        return {
            'sessions_today': {'value': len(sessions_today)},
            'sessions_in_progress': {'value': len(sessions_in_progress)},
            'equipment_issued': {'value': equipment_issued},
            'attendance_rate': {
                'value': round(present_attendance / total_attendance * 100.0, 1) if total_attendance else 0.0,
            },
        }

    def _get_session_list(self, Session):
        records = Session.search([], order='write_date desc', limit=SESSION_LIST_LIMIT)
        return [{
            'id': s.id,
            'room': s.room_id.name or '',
            'course_batch': '%s - %s' % (s.course_id.name or '', s.batch_id.name or ''),
            'instructor': s.faculty_id.name or '',
            'date': fields.Date.to_string(s.date) if s.date else '',
            'state': s.state,
        } for s in records]

    def _get_status_distribution(self, sessions):
        status_labels = dict(sessions._fields['state'].selection)
        counter = Counter(sessions.mapped('state'))
        ordered = [key for key, _label in sessions._fields['state'].selection if key in counter]
        return {
            'labels': [status_labels.get(k, k) for k in ordered],
            'values': [counter[k] for k in ordered],
        }

    def _get_lab_type_distribution(self):
        Room = self.env['lab.room'].sudo()
        rooms = Room.search([])
        counter = Counter(rooms.mapped('lab_type'))
        ordered = sorted(counter, key=lambda k: counter[k], reverse=True)
        return {
            'labels': [LAB_TYPE_LABELS.get(k, k) for k in ordered],
            'values': [counter[k] for k in ordered],
        }

    def _get_attendance_distribution(self):
        Attendance = self.env['lab.attendance'].sudo()
        attendance = Attendance.search([])
        status_labels = dict(Attendance._fields['status'].selection)
        counter = Counter(attendance.mapped('status'))
        ordered = [key for key, _label in Attendance._fields['status'].selection if key in counter]
        return {
            'labels': [status_labels.get(k, k) for k in ordered],
            'values': [counter[k] for k in ordered],
        }

    def _get_monthly_session_trend(self, sessions):
        labels, values = [], []
        for i in range(MONTH_WINDOW - 1, -1, -1):
            month_start, month_end = self._month_bounds(i)
            month_records = sessions.filtered(
                lambda s: s.date and month_start <= s.date <= month_end)
            labels.append(month_start.strftime('%b'))
            values.append(len(month_records))
        return {'labels': labels, 'values': values}

    def _get_equipment_attention(self):
        Equipment = self.env['lab.equipment'].sudo()
        items = Equipment.search(
            [('condition', 'in', ('damaged', 'under_repair'))], limit=EQUIPMENT_ATTENTION_LIMIT)
        condition_labels = dict(Equipment._fields['condition'].selection)
        return [{
            'name': e.name,
            'lab_room': e.lab_id.name or '',
            'condition': condition_labels.get(e.condition, e.condition),
            'quantity_available': e.quantity_available,
        } for e in items]

    def _get_secondary_stats(self):
        Result = self.env['lab.experiment.result'].sudo()
        results = Result.search([('max_marks', '>', 0)])
        if results:
            avg_pct = round(sum(
                r.marks_obtained / r.max_marks * 100.0 for r in results) / len(results), 1)
        else:
            avg_pct = 0.0

        Equipment = self.env['lab.equipment'].sudo()
        equipment_under_repair_count = Equipment.search_count(
            [('condition', 'in', ('damaged', 'under_repair'))])

        Room = self.env['lab.room'].sudo()
        active_rooms_count = Room.search_count([('active', '=', True)])

        return {
            'avg_experiment_score_pct': avg_pct,
            'equipment_under_repair_count': equipment_under_repair_count,
            'active_rooms_count': active_rooms_count,
        }

    def _get_recent_activity(self):
        activities = []

        Session = self.env['lab.session'].sudo()
        session_labels = dict(Session._fields['state'].selection)
        for session in Session.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': 'Session %s (%s) - %s' % (
                    session.name, session.room_id.name or '', session_labels.get(session.state, session.state)),
                'date': fields.Datetime.to_string(session.write_date),
                'kind': SESSION_STATUS_KIND.get(session.state, 'info'),
            })

        Issue = self.env['lab.equipment.issue'].sudo()
        issue_labels = dict(Issue._fields['state'].selection)
        for issue in Issue.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': 'Equipment %s - %s' % (
                    issue.equipment_id.name or '', issue_labels.get(issue.state, issue.state)),
                'date': fields.Datetime.to_string(issue.write_date),
                'kind': ISSUE_STATUS_KIND.get(issue.state, 'info'),
            })

        activities.sort(key=lambda a: a['date'], reverse=True)
        return activities[:RECENT_ACTIVITY_LIMIT]
