# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

MONTH_WINDOW = 6
STUDENT_LIST_LIMIT = 10
TOP_PROGRAMS_LIMIT = 5
RECENT_ACTIVITY_LIMIT = 8


class ScholarshipDashboard(models.AbstractModel):
    """Server-side aggregation for the Scholarship Statistics & Analytics
    client action. Every number here is a live query against
    bxi.scholarship.program / bxi.student.scholarship - nothing is cached,
    so the dashboard always matches the underlying list views.
    """
    _name = 'bxi.scholarship.dashboard'
    _description = 'Scholarship Dashboard'

    def _month_bounds(self, months_ago=0):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1) - relativedelta(months=months_ago)
        month_end = month_start + relativedelta(months=1) - relativedelta(days=1)
        return month_start, month_end

    @api.model
    def get_dashboard_data(self):
        Scholarship = self.env['bxi.student.scholarship'].sudo()
        approved_domain = [('approval_status', '=', 'approved'), ('active', '=', True)]
        approved = Scholarship.search(approved_domain)
        return {
            'kpis': self._get_kpis(approved),
            'student_list': self._get_student_list(Scholarship),
            'charts': {
                'type_distribution': self._get_type_distribution(Scholarship, approved_domain),
                'class_wise_recipients': self._get_class_wise_recipients(Scholarship, approved_domain),
                'monthly_disbursement_trend': self._get_monthly_disbursement_trend(approved),
                'budget_allocation': self._get_budget_allocation(),
            },
            'top_programs': self._get_top_programs(),
            'stats': self._get_secondary_stats(approved, Scholarship),
            'recent_activity': self._get_recent_activity(Scholarship),
        }

    @api.model
    def action_export_full_report(self):
        scholarships = self.env['bxi.student.scholarship'].sudo().search([('active', '=', True)])
        return self.env.ref('bxi_school_scholarship.action_report_scholarship').report_action(scholarships)

    def _get_kpis(self, approved):
        Program = self.env['bxi.scholarship.program'].sudo()
        active_programs = Program.search([('active', '=', True)])
        total_budget = sum(active_programs.mapped('budget_amount'))
        total_disbursed = sum(approved.mapped('scholarship_amount'))
        return {
            'total_scholarships_active': {'value': len(active_programs)},
            'total_recipients': {'value': len(approved.mapped('student_id'))},
            'total_amount_disbursed': {'value': total_disbursed},
            'budget_utilization': {
                'value': round(total_disbursed / total_budget * 100.0, 1) if total_budget else 0.0,
            },
        }

    def _get_student_list(self, Scholarship):
        records = Scholarship.search([], order='write_date desc', limit=STUDENT_LIST_LIMIT)
        return [{
            'id': s.id,
            'student_name': s.student_id.name,
            'scholarship_name': s.program_id.name or dict(
                Scholarship._fields['scholarship_type'].selection).get(s.scholarship_type, ''),
            'coverage_type': s.coverage_type,
            'coverage_percentage': s.coverage_percentage,
            'fixed_amount': s.fixed_amount,
            'approval_status': s.approval_status,
            'balance': s.net_payable_amount,
        } for s in records]

    def _get_type_distribution(self, Scholarship, approved_domain):
        type_labels = dict(Scholarship._fields['scholarship_type'].selection)
        groups = Scholarship._read_group(approved_domain, groupby=['scholarship_type'], aggregates=['__count'])
        return {
            'labels': [type_labels.get(t, t) for t, _c in groups],
            'values': [c for _t, c in groups],
        }

    def _get_class_wise_recipients(self, Scholarship, approved_domain):
        groups = Scholarship._read_group(
            approved_domain + [('class_id', '!=', False)],
            groupby=['class_id'], aggregates=['__count'])
        groups = sorted(groups, key=lambda g: g[0].name or '')
        return {
            'labels': [class_id.name for class_id, _c in groups],
            'values': [c for _cls, c in groups],
        }

    def _get_monthly_disbursement_trend(self, approved):
        labels, values = [], []
        for i in range(MONTH_WINDOW - 1, -1, -1):
            month_start, month_end = self._month_bounds(i)
            month_records = approved.filtered(
                lambda s: s.approval_date and month_start <= s.approval_date <= month_end)
            labels.append(month_start.strftime('%b'))
            values.append(sum(month_records.mapped('scholarship_amount')))
        return {'labels': labels, 'values': values}

    def _get_budget_allocation(self):
        Program = self.env['bxi.scholarship.program'].sudo()
        active_programs = Program.search([('active', '=', True)])
        total_budget = sum(active_programs.mapped('budget_amount'))
        total_disbursed = sum(active_programs.mapped('amount_disbursed'))
        return {
            'total_budget': total_budget,
            'amount_disbursed': total_disbursed,
            'remaining_budget': total_budget - total_disbursed,
        }

    def _get_top_programs(self):
        Program = self.env['bxi.scholarship.program'].sudo()
        programs = Program.search([('active', '=', True)])
        programs = programs.sorted(key=lambda p: p.budget_utilization, reverse=True)[:TOP_PROGRAMS_LIMIT]
        return [{
            'name': program.name,
            'recipients': program.recipient_count,
            'budget': program.budget_amount,
            'utilization': round(program.budget_utilization, 1),
        } for program in programs]

    def _get_secondary_stats(self, approved, Scholarship):
        recipient_count = len(approved.mapped('student_id'))
        total_disbursed = sum(approved.mapped('scholarship_amount'))
        highest_amount = max(approved.mapped('scholarship_amount'), default=0.0)
        pending_count = Scholarship.search_count([('approval_status', '=', 'pending')])
        return {
            'average_per_student': (total_disbursed / recipient_count) if recipient_count else 0.0,
            'highest_amount': highest_amount,
            'applications_pending': pending_count,
        }

    def _get_recent_activity(self, Scholarship):
        status_kind = {
            'approved': 'success',
            'rejected': 'danger',
            'pending': 'warning',
            'draft': 'info',
        }
        status_labels = dict(Scholarship._fields['approval_status'].selection)
        activities = []
        for scholarship in Scholarship.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': '%s - %s' % (
                    scholarship.student_id.name, status_labels.get(
                        scholarship.approval_status, scholarship.approval_status)),
                'user': scholarship.approved_by.name or '',
                'date': fields.Datetime.to_string(scholarship.write_date),
                'kind': status_kind.get(scholarship.approval_status, 'info'),
            })
        return activities
