# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Admin dashboard - attendance: every student's attendance over a date
range, either one row per student (counts and percentage) or one row per
period mark. Dates and percentages follow the same rules as the parent
app and the per-student summary (hr.attendance._attendance_date and
op.student._summarize_attendance_rows)."""
from collections import Counter

from odoo import fields, http
from odoo.fields import Domain
from odoo.http import request
from odoo.tools import SQL

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth

from .admin_classes import VIEW_GROUPS
from .common import date_str, parse_date, parse_pagination, parse_sort, ref, resolve_record, running_enrollments
from .dashboard import _allowed

STATUSES = ('present', 'absent', 'late', 'excused')
MAX_RANGE_DAYS = 366
SUMMARY_SORTS = ('name', 'gr_no', 'class', 'total', 'present', 'absent', 'late', 'excused', 'percentage')
RECORD_SORTS = ('date',)


def _forbidden():
    return api_error('Not authorized for attendance reports.', status=403, code='forbidden')


def _percentage(present, total):
    return round(100.0 * present / total, 1) if total else 0.0


def _bad_request(message, code):
    return api_error(message, status=400, code=code)


class BxiApiSupportAdminAttendanceController(http.Controller):

    @http.route('/api/v1/admin/attendance', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_attendance(self, view='summary', date_from=None, date_to=None, class_id=None, section_id=None,
                        student_id=None, subject_id=None, status=None, q=None, include_unmarked=None,
                        max_percentage=None, sort=None, **kwargs):
        """All students' attendance between date_from and date_to (default:
        the 1st of this month to today).

        ?view=summary (default): one row per student with their status
        counts and percentage; `totals` covers every matching student, not
        just this page. ?include_unmarked=1 also lists enrolled students
        with no marks in the range; ?max_percentage=75 keeps only marked
        students at or below 75%.

        ?view=records: one row per period mark, newest first; ?status=
        filters by present/absent/late/excused.
        """
        env = request.env
        if not _allowed(env.user, VIEW_GROUPS):
            return _forbidden()
        if view not in ('summary', 'records'):
            return _bad_request('view must be summary or records.', 'invalid_view')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error

        today = fields.Date.context_today(env.user)
        start, error = parse_date(date_from, 'date_from') if date_from else (today.replace(day=1), None)
        if error:
            return error
        end, error = parse_date(date_to, 'date_to') if date_to else (today, None)
        if error:
            return error
        if start > end:
            return _bad_request('date_from must be on or before date_to.', 'invalid_date_range')
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            return _bad_request('The date range can span at most %s days.' % MAX_RANGE_DAYS, 'range_too_large')

        filters = {}
        for param, model, value in (('class_id', 'op.course', class_id), ('section_id', 'op.batch', section_id),
                                    ('student_id', 'op.student', student_id), ('subject_id', 'op.subject', subject_id)):
            filters[param], error = resolve_record(env, model, value, param)
            if error:
                return error

        Attendance = env['hr.attendance'].sudo()
        domain = (Domain('student_id', '!=', False) & Domain('status', '!=', False)
                  & Attendance._date_range_domain(start, end))
        if filters['class_id']:
            domain &= Domain('class_id', '=', filters['class_id'].id)
        if filters['section_id']:
            domain &= Domain('section_id', '=', filters['section_id'].id)
        if filters['student_id']:
            domain &= Domain('student_id', '=', filters['student_id'].id)
        if filters['subject_id']:
            domain &= Domain('session_id.subject_id', '=', filters['subject_id'].id)
        if q:
            domain &= Domain('student_id.name', 'ilike', q) | Domain('student_id.gr_no', 'ilike', q)

        range_data = {'date_from': fields.Date.to_string(start), 'date_to': fields.Date.to_string(end)}
        if view == 'records':
            if status:
                if status not in STATUSES:
                    return _bad_request('status must be one of %s.' % ', '.join(STATUSES), 'invalid_status')
                domain &= Domain('status', '=', status)
            order, error = parse_sort(sort, RECORD_SORTS, 'date desc')
            if error:
                return error
            return self._records(Attendance, domain, order[1], limit, offset, range_data)

        if status:
            return _bad_request('status only applies to view=records.', 'invalid_status')
        threshold = None
        if max_percentage not in (None, ''):
            try:
                threshold = float(max_percentage)
            except ValueError:
                return _bad_request('max_percentage must be a number.', 'invalid_max_percentage')
        order, error = parse_sort(sort, SUMMARY_SORTS, 'name asc')
        if error:
            return error
        return self._summary(env, Attendance, domain, filters, q, include_unmarked in ('1', 'true', 'True'),
                             threshold, order, limit, offset, range_data)

    # -- per student ---------------------------------------------------------------

    def _summary(self, env, Attendance, domain, filters, q, include_unmarked, threshold, order, limit, offset,
                 range_data):
        counts = {}
        for student, status, count in Attendance._read_group(domain, ['student_id', 'status'], ['__count']):
            counts.setdefault(student.id, Counter())[status] = count
        student_ids = set(counts)
        if include_unmarked:
            # Everyone currently enrolled in the filtered class/section,
            # the same scope hr.attendance.class_id/section_id reflect.
            enrolled = Domain('state', '=', 'running')
            if filters['class_id']:
                enrolled &= Domain('course_id', '=', filters['class_id'].id)
            if filters['section_id']:
                enrolled &= Domain('batch_id', '=', filters['section_id'].id)
            if filters['student_id']:
                enrolled &= Domain('student_id', '=', filters['student_id'].id)
            if q:
                enrolled &= Domain('student_id.name', 'ilike', q) | Domain('student_id.gr_no', 'ilike', q)
            student_ids |= set(env['op.student.course'].sudo().search(enrolled).student_id.ids)

        students = env['op.student'].sudo().browse(sorted(student_ids))
        enrollments = running_enrollments(env, students)
        rows = []
        for student in students:
            status_counts = counts.get(student.id, Counter())
            total = sum(status_counts.values())
            percentage = _percentage(status_counts['present'], total)
            if threshold is not None and (not total or percentage > threshold):
                continue
            enrollment = enrollments.get(student.id)
            rows.append({
                'student': ref(student),
                'gr_no': student.gr_no or None,
                'class': ref(enrollment.course_id) if enrollment else None,
                'section': ref(enrollment.batch_id) if enrollment else None,
                'roll_number': (enrollment.roll_number or None) if enrollment else None,
                'total': total,
                **{status: status_counts[status] for status in STATUSES},
                'percentage': percentage,
            })

        column, direction = order
        if column == 'name':
            key = lambda r: (r['student']['name'] or '').lower()
        elif column == 'gr_no':
            key = lambda r: r['gr_no'] or ''
        elif column == 'class':
            # Class, section, then roll number - students without one last.
            key = lambda r: ((r['class'] or {}).get('name') or '', (r['section'] or {}).get('name') or '',
                             r['roll_number'] is None, r['roll_number'] or '')
        else:
            key = lambda r: r[column]
        # Stable two-pass sort: name ascending breaks ties for every column.
        rows.sort(key=lambda r: ((r['student']['name'] or '').lower(), r['student']['id']))
        rows.sort(key=key, reverse=direction == 'desc')

        totals = {status: sum(r[status] for r in rows) for status in STATUSES}
        marked = sum(totals.values())
        return api_response(dict(range_data, view='summary', totals={
            'students': len(rows),
            'marked': marked,
            **totals,
            'percentage': _percentage(totals['present'], marked),
        }, students=rows[offset:offset + limit]), meta={'total': len(rows), 'limit': limit, 'offset': offset})

    # -- per period mark -----------------------------------------------------------

    def _records(self, Attendance, domain, direction, limit, offset, range_data):
        total = Attendance.search_count(domain)
        # A mark's date lives on its period (or, without one, in its local
        # check-in), so the page is ordered in SQL on that same expression.
        direction = SQL('DESC') if direction == 'desc' else SQL('ASC')
        tz = Attendance.env.tz.zone
        Attendance.env.cr.execute(SQL(
            """SELECT a.id FROM hr_attendance a
               LEFT JOIN op_session s ON s.id = a.session_id
               WHERE a.id IN %(ids)s
               ORDER BY COALESCE(s.session_date, (a.check_in AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date) %(dir)s,
                        COALESCE(s.start_datetime, a.check_in) %(dir)s NULLS LAST, a.id %(dir)s
               LIMIT %(limit)s OFFSET %(offset)s""",
            ids=Attendance._search(domain).subselect(), tz=tz, dir=direction, limit=limit, offset=offset))
        attendances = Attendance.browse([row[0] for row in Attendance.env.cr.fetchall()])
        items = []
        for attendance in attendances:
            session = attendance.session_id
            items.append({
                'id': attendance.id,
                'date': date_str(attendance._attendance_date()),
                'student': ref(attendance.student_id),
                'gr_no': attendance.student_id.gr_no or None,
                'class': ref(attendance.class_id),
                'section': ref(attendance.section_id),
                'session_id': session.id or None,
                'period': session.timing_id.display_name if session.timing_id else None,
                'subject': ref(session.subject_id),
                'teacher': ref(session.faculty_id),
                'status': attendance.status,
                'check_in': date_str(attendance.check_in),
                'check_out': date_str(attendance.check_out),
                'remark': attendance.remark or None,
            })
        return api_response(dict(range_data, view='records', records=items),
                            meta={'total': total, 'limit': limit, 'offset': offset})
