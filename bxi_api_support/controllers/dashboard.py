# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Management dashboards for the app: each wraps the get_dashboard_data()
the module's own backend dashboard already serves, gated by that module's
staff groups - plus a school-wide attendance snapshot, which has no
backend dashboard of its own."""
from collections import Counter

from odoo import fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth

from ..models.res_users import COORDINATOR_GROUPS, PERMISSION_GROUPS

# name -> (dashboard model, groups allowed besides base.group_system)
DASHBOARDS = {
    'fees': ('bxi.fee.dashboard', PERMISSION_GROUPS['fee_staff']),
    'academic': ('bxi.academic.dashboard', COORDINATOR_GROUPS),
    'assessments': ('bxi.assessment.dashboard', COORDINATOR_GROUPS),
    'students': ('bxi.student.dashboard', PERMISSION_GROUPS['admission_staff'] + COORDINATOR_GROUPS),
    'transport': ('bxi.transport.dashboard', PERMISSION_GROUPS['transport_staff']),
    'canteen': ('bxi.canteen.dashboard', PERMISSION_GROUPS['canteen_staff']),
    'uniform': ('bxi.uniform.dashboard', PERMISSION_GROUPS['uniform_staff']),
    'health': ('bxi.health.dashboard', PERMISSION_GROUPS['health_staff']),
    'lab': ('lab.dashboard', PERMISSION_GROUPS['lab_staff']),
    'rte': ('bxi.rte.dashboard', PERMISSION_GROUPS['rte_staff']),
    'scholarship': ('bxi.scholarship.dashboard', PERMISSION_GROUPS['scholarship_staff']),
    'visitor': ('bxi.visitor.dashboard', PERMISSION_GROUPS['visitor_staff']),
}
ATTENDANCE_GROUPS = COORDINATOR_GROUPS


def _allowed(user, groups):
    return user.has_group('base.group_system') or any(user.has_group(g) for g in groups)


class BxiApiSupportDashboardController(http.Controller):

    @http.route('/api/v1/dashboards', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_dashboards(self, **kwargs):
        """The dashboards this login may open (installed modules only)."""
        user = request.env.user
        names = [name for name, (model, groups) in DASHBOARDS.items()
                 if model in request.env and _allowed(user, groups)]
        if _allowed(user, ATTENDANCE_GROUPS):
            names.append('attendance')
        return api_response({'dashboards': sorted(names)})

    @http.route('/api/v1/dashboards/attendance', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def attendance_dashboard(self, date=None, **kwargs):
        """Today's (or ?date=) periods, how many are fully marked, and the
        status split per class."""
        if not _allowed(request.env.user, ATTENDANCE_GROUPS):
            return api_error('Not authorized for this dashboard.', status=403, code='forbidden')
        try:
            day = fields.Date.to_date(date) if date else fields.Date.context_today(request.env.user)
        except ValueError:
            return api_error('date must be YYYY-MM-DD.', status=400, code='invalid_date')
        sessions = request.env['op.session'].sudo().search([('session_date', '=', day), ('state', '!=', 'cancel')])
        attendances = request.env['hr.attendance'].sudo().search([
            ('session_id', 'in', sessions.ids), ('status', '!=', False),
        ])
        marked_sessions = set(attendances.session_id.ids)
        by_class = {}
        for attendance in attendances:
            key = attendance.session_id.course_id.display_name or '-'
            by_class.setdefault(key, Counter())[attendance.status] += 1
        totals = Counter(attendances.mapped('status'))
        marked = sum(totals.values())
        return api_response({
            'date': fields.Date.to_string(day),
            'periods': len(sessions),
            'periods_marked': len(marked_sessions),
            'periods_unmarked': len(sessions) - len(marked_sessions),
            'status_totals': dict(totals),
            'present_percentage': round(100.0 * totals['present'] / marked, 1) if marked else 0.0,
            'by_class': [{'class': name, **dict(counts)} for name, counts in sorted(by_class.items())],
        })

    @http.route('/api/v1/dashboards/<string:name>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def dashboard(self, name, **kwargs):
        if name not in DASHBOARDS:
            return api_error(f"Unknown dashboard '{name}'.", status=404, code='not_found')
        model, groups = DASHBOARDS[name]
        if model not in request.env:
            return api_error(f"The '{name}' dashboard's module is not installed.", status=404, code='not_installed')
        if not _allowed(request.env.user, groups):
            return api_error('Not authorized for this dashboard.', status=403, code='forbidden')
        return api_response(request.env[model].sudo().get_dashboard_data())
