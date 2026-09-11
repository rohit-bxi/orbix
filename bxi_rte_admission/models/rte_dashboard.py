# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from collections import Counter

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

MONTH_WINDOW = 6
APPLICATION_LIST_LIMIT = 10
TOP_COURSES_LIMIT = 5
RECENT_ACTIVITY_LIMIT = 8

RTE_ACTIVE_SEAT_STATES = ('allotted', 'confirmed', 'admitted')

LOTTERY_BATCH_STATUS_KIND = {
    'draft': 'info',
    'ready': 'warning',
    'run': 'warning',
    'published': 'success',
}
GRIEVANCE_STATUS_KIND = {
    'draft': 'info',
    'submitted': 'warning',
    'escalated_jd': 'danger',
    'resolved': 'success',
    'rejected': 'danger',
}
REIMBURSEMENT_STATUS_KIND = {
    'draft': 'info',
    'submitted': 'warning',
    'approved': 'success',
    'paid': 'success',
    'rejected': 'danger',
}


class RteDashboard(models.AbstractModel):
    """Server-side aggregation for the RTE Admission Dashboard client
    action. Every number here is a live query against op.admission /
    rte.lottery.batch / rte.grievance / rte.reimbursement.claim - nothing
    is cached, so the dashboard always matches the underlying list views.
    """
    _name = 'bxi.rte.dashboard'
    _description = 'RTE Admission Dashboard'

    def _month_bounds(self, months_ago=0):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1) - relativedelta(months=months_ago)
        month_end = month_start + relativedelta(months=1) - relativedelta(days=1)
        return month_start, month_end

    @api.model
    def get_dashboard_data(self):
        Admission = self.env['op.admission'].sudo()
        rte_domain = [('is_rte_applicant', '=', True)]
        applicants = Admission.search(rte_domain)
        return {
            'kpis': self._get_kpis(applicants),
            'application_list': self._get_application_list(Admission, rte_domain),
            'charts': {
                'status_distribution': self._get_status_distribution(applicants),
                'category_distribution': self._get_category_distribution(applicants),
                'monthly_application_trend': self._get_monthly_application_trend(applicants),
                'seat_allocation': self._get_seat_allocation(applicants),
            },
            'top_courses': self._get_top_courses(applicants),
            'stats': self._get_secondary_stats(),
            'recent_activity': self._get_recent_activity(),
        }

    def _get_kpis(self, applicants):
        Course = self.env['op.course'].sudo()
        active_courses = Course.search([('rte_active', '=', True)])
        total_seats = sum(active_courses.mapped('rte_seats'))
        seats_filled = len(applicants.filtered(lambda a: a.rte_state in RTE_ACTIVE_SEAT_STATES))
        return {
            'total_rte_applicants': {'value': len(applicants)},
            'total_seats_reserved': {'value': total_seats},
            'seats_filled': {'value': seats_filled},
            'seat_utilization': {
                'value': round(seats_filled / total_seats * 100.0, 1) if total_seats else 0.0,
            },
        }

    def _get_application_list(self, Admission, rte_domain):
        records = Admission.search(rte_domain, order='write_date desc', limit=APPLICATION_LIST_LIMIT)
        category_labels = dict(self.env['op.parent']._fields['rte_category'].selection)
        return [{
            'id': a.id,
            'student_name': a.partner_id.name or a.application_number,
            'course_name': a.course_id.name or '',
            'category': category_labels.get(a.rte_parent_id.rte_category, '') or '-',
            'rte_state': a.rte_state,
        } for a in records]

    def _get_status_distribution(self, applicants):
        status_labels = dict(applicants._fields['rte_state'].selection)
        counter = Counter(applicants.mapped('rte_state'))
        ordered = [key for key, _label in applicants._fields['rte_state'].selection if key in counter]
        return {
            'labels': [status_labels.get(k, k) for k in ordered],
            'values': [counter[k] for k in ordered],
        }

    def _get_category_distribution(self, applicants):
        category_labels = dict(self.env['op.parent']._fields['rte_category'].selection)
        counter = Counter(
            a.rte_parent_id.rte_category for a in applicants if a.rte_parent_id.rte_category)
        ordered = sorted(counter, key=lambda k: counter[k], reverse=True)
        return {
            'labels': [category_labels.get(k, k) for k in ordered],
            'values': [counter[k] for k in ordered],
        }

    def _get_monthly_application_trend(self, applicants):
        labels, values = [], []
        for i in range(MONTH_WINDOW - 1, -1, -1):
            month_start, month_end = self._month_bounds(i)
            month_records = applicants.filtered(
                lambda a: a.create_date and month_start <= a.create_date.date() <= month_end)
            labels.append(month_start.strftime('%b'))
            values.append(len(month_records))
        return {'labels': labels, 'values': values}

    def _get_seat_allocation(self, applicants):
        Course = self.env['op.course'].sudo()
        active_courses = Course.search([('rte_active', '=', True)])
        total_seats = sum(active_courses.mapped('rte_seats'))
        seats_filled = len(applicants.filtered(lambda a: a.rte_state in RTE_ACTIVE_SEAT_STATES))
        return {
            'total_seats': total_seats,
            'seats_filled': seats_filled,
            'seats_remaining': max(total_seats - seats_filled, 0),
        }

    def _get_top_courses(self, applicants):
        Course = self.env['op.course'].sudo()
        courses = Course.search([('rte_active', '=', True)])
        rows = []
        for course in courses:
            course_applicants = applicants.filtered(lambda a: a.course_id.id == course.id)
            rows.append({
                'name': course.name,
                'seats': course.rte_seats,
                'applicants': len(course_applicants),
                'utilization': round(
                    len(course_applicants) / course.rte_seats * 100.0, 1) if course.rte_seats else 0.0,
            })
        rows.sort(key=lambda r: r['applicants'], reverse=True)
        return rows[:TOP_COURSES_LIMIT]

    def _get_secondary_stats(self):
        Claim = self.env['rte.reimbursement.claim'].sudo()
        Grievance = self.env['rte.grievance'].sudo()
        pending_amount = sum(Claim.search([('state', '=', 'submitted')]).mapped('amount'))
        paid_amount = sum(Claim.search([('state', '=', 'paid')]).mapped('amount'))
        open_grievances = Grievance.search_count([('state', 'in', ('submitted', 'escalated_jd'))])
        return {
            'reimbursement_pending_amount': pending_amount,
            'reimbursement_paid_amount': paid_amount,
            'open_grievances': open_grievances,
        }

    def _get_recent_activity(self):
        activities = []

        Batch = self.env['rte.lottery.batch'].sudo()
        batch_labels = dict(Batch._fields['state'].selection)
        for batch in Batch.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': 'Lottery Batch %s (%s) - %s' % (
                    batch.name, batch.course_id.name, batch_labels.get(batch.state, batch.state)),
                'date': fields.Datetime.to_string(batch.write_date),
                'kind': LOTTERY_BATCH_STATUS_KIND.get(batch.state, 'info'),
            })

        Grievance = self.env['rte.grievance'].sudo()
        grievance_labels = dict(Grievance._fields['state'].selection)
        for grievance in Grievance.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': 'Grievance %s - %s' % (
                    grievance.name, grievance_labels.get(grievance.state, grievance.state)),
                'date': fields.Datetime.to_string(grievance.write_date),
                'kind': GRIEVANCE_STATUS_KIND.get(grievance.state, 'info'),
            })

        Claim = self.env['rte.reimbursement.claim'].sudo()
        claim_labels = dict(Claim._fields['state'].selection)
        for claim in Claim.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': 'Reimbursement Claim %s - %s' % (
                    claim.name, claim_labels.get(claim.state, claim.state)),
                'date': fields.Datetime.to_string(claim.write_date),
                'kind': REIMBURSEMENT_STATUS_KIND.get(claim.state, 'info'),
            })

        activities.sort(key=lambda a: a['date'], reverse=True)
        return activities[:RECENT_ACTIVITY_LIMIT]
