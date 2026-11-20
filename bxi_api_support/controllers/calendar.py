# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""School calendar: public holidays (resource.calendar.leaves without a
resource - the school-wide closures bxi_academic_management manages) and,
per student, holidays + exams + events + PTMs + homework deadlines +
online tests on one timeline."""
from datetime import datetime, time, timedelta

import pytz

from odoo import fields, http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth

from .academic_admin import _holiday_dict
from .common import date_str, get_app_student, running_enrollment
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
        # start_date / end_date are the school's days (the Edit Holiday
        # screen's dates); date_from / date_to stay the stored UTC bounds.
        return api_response({'holidays': [_holiday_dict(leave) for leave in _holidays(start, end)]})

    @http.route('/api/v1/calendar', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def calendar(self, student_id=None, date_from=None, date_to=None, **kwargs):
        """Everything on the student's calendar between date_from and
        date_to (default: the next 90 days), sorted by start: holiday, exam,
        ptm, event, assignment (homework due) and assessment (online test).
        A student's own login may leave student_id out."""
        student, error = get_app_student(request.env, student_id)
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
            meetings = meetings.filtered(lambda m: m._bxi_covers(enrollment.course_id, enrollment.batch_id))
            items += [_item('ptm', m.id, m.name, m.start_datetime, m.end_datetime, venue=m.venue)
                      for m in meetings]

        # Homework due in the range (the Smart Calendar's "History Essay").
        assignments = request.env['op.assignment'].sudo().search([
            ('allocation_ids', 'in', student.id), ('state', 'in', ('publish', 'finish')),
            ('submission_date', '>=', start), ('submission_date', '<=', end)])
        items += [_item('assignment', a.id, a.name, a.submission_date, a.submission_date,
                        subject=a.subject_id.name or None) for a in assignments]

        # Online tests (bxi_assessment_hub) the student is assigned to.
        if 'bxi.assessment.session' in request.env:
            tz = pytz.timezone(request.env.user.tz or request.env.company.sudo().resource_calendar_id.tz or 'UTC')
            sessions = request.env['bxi.assessment.session'].sudo().search([
                ('student_ids', 'in', student.id), ('state', '!=', 'cancelled'),
                ('exam_date', '>=', start.date()), ('exam_date', '<=', end.date())])
            for session in sessions:
                hours = int(session.exam_time)
                local = tz.localize(datetime.combine(
                    session.exam_date, time(hours, int(round((session.exam_time - hours) * 60)) % 60)))
                begin = local.astimezone(pytz.utc).replace(tzinfo=None)
                items.append(_item('assessment', session.id, session.exam_id.name, begin,
                                   begin + timedelta(minutes=session.exam_id.duration or 60),
                                   subject=session.exam_id.subject_id.name or None))

        events = request.env['event.event'].sudo().search(Domain.AND([
            visible_events_domain(request.env),
            Domain('date_begin', '<=', end), Domain('date_end', '>=', start),
        ]))
        items += [_item('event', e.id, e.name, e.date_begin, e.date_end, category=e.event_category) for e in events]

        items.sort(key=lambda item: item['start'] or '')
        return api_response({'student_id': student.id, 'date_from': date_str(start.date()),
                             'date_to': date_str(end.date()), 'items': items})
