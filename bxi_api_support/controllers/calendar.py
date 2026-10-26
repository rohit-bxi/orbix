# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""School calendar: public holidays (resource.calendar.leaves without a
resource - the school-wide closures bxi_academic_management manages) and,
per student, holidays + exams + events + PTMs on one timeline."""
from datetime import datetime, time, timedelta

from odoo import fields, http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth

from .common import date_str, get_viewable_student, running_enrollment
from .event import _visible_domain as visible_events_domain

DEFAULT_RANGE_DAYS = 90


def _parse_range(date_from, date_to):
    """(start, end) datetimes covering whole days, default today..+90d, or
    raises ValueError for a malformed date."""
    start = fields.Date.to_date(date_from) if date_from else fields.Date.today()
    end = fields.Date.to_date(date_to) if date_to else start + timedelta(days=DEFAULT_RANGE_DAYS)
    return datetime.combine(start, time.min), datetime.combine(end, time.max)


def _holidays(start, end):
    return request.env['resource.calendar.leaves'].sudo().search([
        ('resource_id', '=', False), ('date_from', '<=', end), ('date_to', '>=', start),
        ('company_id', 'in', [False, request.env.company.id]),
    ], order='date_from')


def _item(kind, record_id, title, begin, finish, **extra):
    return dict({'type': kind, 'id': record_id, 'title': title,
                 'start': date_str(begin), 'end': date_str(finish)}, **extra)


class BxiApiSupportCalendarController(http.Controller):

    @http.route('/api/v1/calendar/holidays', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def holidays(self, date_from=None, date_to=None, **kwargs):
        try:
            start, end = _parse_range(date_from, date_to)
        except ValueError:
            return api_error('date_from/date_to must be YYYY-MM-DD.', status=400, code='invalid_date')
        return api_response({'holidays': [{
            'id': leave.id,
            'name': leave.name,
            'description': leave.description or None,
            'date_from': date_str(leave.date_from),
            'date_to': date_str(leave.date_to),
        } for leave in _holidays(start, end)]})

    @http.route('/api/v1/calendar', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def calendar(self, student_id=None, date_from=None, date_to=None, **kwargs):
        """Everything on the student's calendar between date_from and
        date_to (default: the next 90 days), sorted by start."""
        student, error = get_viewable_student(request.env, student_id)
        if error:
            return error
        try:
            start, end = _parse_range(date_from, date_to)
        except ValueError:
            return api_error('date_from/date_to must be YYYY-MM-DD.', status=400, code='invalid_date')
        enrollment = running_enrollment(student)
        items = [_item('holiday', h.id, h.name, h.date_from, h.date_to) for h in _holidays(start, end)]

        if enrollment:
            exams = request.env['op.exam'].sudo().search([
                ('session_id.course_id', '=', enrollment.course_id.id),
                ('session_id.state', 'in', ('schedule', 'held', 'done')),
                '|', ('session_id.batch_id', '=', False), ('session_id.batch_id', '=', enrollment.batch_id.id),
                ('start_time', '<=', end), ('end_time', '>=', start), ('state', '!=', 'cancel'),
            ])
            items += [_item('exam', e.id, f'{e.subject_id.name or e.name} exam', e.start_time, e.end_time,
                            session_id=e.session_id.id) for e in exams]

            meetings = request.env['bxi.ptm.meeting'].sudo().search([
                ('class_ids', 'in', enrollment.course_id.id),
                ('start_datetime', '<=', end), ('end_datetime', '>=', start),
            ])
            items += [_item('ptm', m.id, m.name, m.start_datetime, m.end_datetime, venue=m.venue)
                      for m in meetings]

        events = request.env['event.event'].sudo().search(Domain.AND([
            visible_events_domain(request.env),
            Domain('date_begin', '<=', end), Domain('date_end', '>=', start),
        ]))
        items += [_item('event', e.id, e.name, e.date_begin, e.date_end, category=e.event_category) for e in events]

        items.sort(key=lambda item: item['start'] or '')
        return api_response({'student_id': student.id, 'date_from': date_str(start.date()),
                             'date_to': date_str(end.date()), 'items': items})
