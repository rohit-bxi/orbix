# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from collections import defaultdict
from datetime import timedelta

from odoo import fields
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import (
    api_error, api_file_response, api_response, parse_int, require_auth,
)


def _user_can_access_student(env, student):
    """Same rule as the other parent-facing modules: staff (any regular
    backend user), the student themself, or a parent linked to the student.
    """
    user = env.user
    if user.has_group('base.group_user') or student.user_id == user:
        return True
    return bool(env['op.parent'].sudo().search_count([
        ('user_id', '=', user.id), ('student_ids', 'in', student.id),
    ]))


def _sessions_domain(student):
    """The student's periods: those listing them, plus - for periods
    generated from the timetable before it filled in rosters - every period
    of their current section that lists nobody."""
    batches = student.course_detail_ids.filtered(lambda line: line.state == 'running').batch_id
    return ['|', ('student_ids', 'in', student.id),
            '&', ('student_ids', '=', False), ('batch_id', 'in', batches.ids)]


def _subject_attendance(env, rows):
    """The Attendance screen's subject-wise list: per subject, its teacher
    (the one who took most of those periods) and present / marked periods.
    Present counts 'present' marks only, as the summary does."""
    by_subject = defaultdict(list)
    for row in rows:
        by_subject[(row['subject_id'], row['subject'])].append(row)
    sessions = env['op.session'].sudo().browse([r['session_id'] for r in rows if r['session_id']])
    teacher_of = {session.id: session.faculty_id for session in sessions}
    result = []
    for (subject_id, subject), subject_rows in sorted(by_subject.items(), key=lambda kv: kv[0][1] or ''):
        taught = defaultdict(int)
        for row in subject_rows:
            if teacher_of.get(row['session_id']):
                taught[teacher_of[row['session_id']]] += 1
        teacher = max(taught, key=taught.get) if taught else None
        present = len([r for r in subject_rows if r['status'] == 'present'])
        result.append({
            'subject_id': subject_id or None,
            'subject': subject or None,
            'teacher': {'id': teacher.id, 'name': teacher.name} if teacher else None,
            'present': present,
            'late': len([r for r in subject_rows if r['status'] == 'late']),
            'absent': len([r for r in subject_rows if r['status'] == 'absent']),
            'total': len(subject_rows),
            'percentage': round(100.0 * present / len(subject_rows), 1),
        })
    return result


def _holidays(env, date_from, date_to):
    """School-wide closures touching [date_from, date_to] (UTC datetimes)."""
    return env['resource.calendar.leaves'].sudo().search([
        ('resource_id', '=', False), ('date_from', '<=', date_to), ('date_to', '>=', date_from),
        ('company_id', 'in', [False, env.company.id])], order='date_from')


def _ics_escape(value):
    """Text for an iCalendar property (RFC 5545 3.3.11)."""
    text = value or ''
    for char, escaped in (('\\', '\\\\'), (';', '\\;'), (',', '\\,'), ('\n', '\\n')):
        text = text.replace(char, escaped)
    return text


def _get_authorized_student(payload_student_id):
    """The student a /parent/* route reports on. A student signing in to
    the app may leave student_id out: it defaults to their own record."""
    if not payload_student_id:
        own = request.env['op.student'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)
        if own:
            return own, None
        return None, api_error('student_id is required.', status=400, code='missing_student_id')
    student_id, error = parse_int(payload_student_id, 'student_id')
    if error:
        return None, error
    student = request.env['op.student'].sudo().browse(student_id)
    if not student.exists():
        return None, api_error('Student not found.', status=404, code='not_found')
    if not _user_can_access_student(request.env, student):
        return None, api_error('Not authorized for this student.', status=403, code='forbidden')
    return student, None


class BxiParentDataApiController(http.Controller):

    @http.route('/api/v1/parent/exam-results', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def exam_results(self, student_id=None, **kwargs):
        student, error = _get_authorized_student(student_id)
        if error:
            return error
        lines = request.env['op.marksheet.line'].sudo().search([
            ('student_id', '=', student.id),
            ('marksheet_reg_id.state', '=', 'validated'),
        ], order='generated_date desc')
        return api_response({
            'results': [{
                'id': line.id,
                'exam_session': line.marksheet_reg_id.exam_session_id.display_name,
                'generated_date': fields.Date.to_string(line.generated_date),
                'total_marks': line.total_marks,
                'percentage': line.percentage,
                'grade': line.grade,
                'status': line.status,
                'subjects': [{
                    'exam': r.exam_id.display_name,
                    'marks': r.marks,
                    'grade': r.grade,
                    'status': r.status,
                } for r in line.result_line],
            } for line in lines],
        })

    @http.route('/api/v1/parent/attendance', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def attendance(self, student_id=None, date_from=None, date_to=None, **kwargs):
        student, error = _get_authorized_student(student_id)
        if error:
            return error

        date_to_val = fields.Date.from_string(date_to) if date_to else fields.Date.today()
        date_from_val = fields.Date.from_string(date_from) if date_from else date_to_val - timedelta(days=30)

        rows = student._get_attendance_rows(date_from_val, date_to_val)
        summary = student._summarize_attendance_rows(rows)
        # The period just before, as long as this one: "+2% from last month".
        span = date_to_val - date_from_val
        previous = student._summarize_attendance_rows(student._get_attendance_rows(
            date_from_val - span - timedelta(days=1), date_from_val - timedelta(days=1)))

        return api_response({
            'date_from': fields.Date.to_string(date_from_val),
            'date_to': fields.Date.to_string(date_to_val),
            'previous_period': {
                'attendance_percentage': previous['percentage'] if previous['total'] else None,
                'change': round(summary['percentage'] - previous['percentage'], 1) if previous['total'] else None,
            },
            'subjects': _subject_attendance(request.env, rows),
            'summary': {
                'total': summary['total'],
                'present': summary['present'],
                'absent': summary['absent'],
                'late': summary['late'],
                'excused': summary['excused'],
                'attendance_percentage': summary['percentage'],
            },
            'days': [{
                'date': fields.Date.to_string(day['date']),
                'status': day['status'],
                'periods': day['periods'],
                # Why the day was missed, when a teacher noted it ("Medical leave").
                'remark': next((r['remark'] for r in rows if r['date'] == day['date'] and r['remark']), None),
            } for day in summary['days']],
            'records': [{
                'date': fields.Date.to_string(row['date']),
                'session_id': row['session_id'],
                'period': row['period'],
                'subject': row['subject'],
                'status': row['status'],
                # Kept for clients built against the old op.attendance.line shape.
                'present': row['status'] == 'present',
                'absent': row['status'] == 'absent',
                'late': row['status'] == 'late',
                'excused': row['status'] == 'excused',
                'remark': row['remark'],
            } for row in rows],
        })

    @http.route('/api/v1/parent/timetable', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def timetable(self, student_id=None, date_from=None, date_to=None, **kwargs):
        student, error = _get_authorized_student(student_id)
        if error:
            return error

        date_from_val = fields.Datetime.from_string(date_from) if date_from else fields.Datetime.now()
        date_to_val = fields.Datetime.from_string(date_to) if date_to else date_from_val + timedelta(days=7)

        sessions = request.env['op.session'].sudo().search(_sessions_domain(student) + [
            ('start_datetime', '>=', date_from_val),
            ('start_datetime', '<=', date_to_val),
            ('state', '!=', 'cancel'),
        ], order='start_datetime asc')
        holidays = _holidays(request.env, date_from_val, date_to_val)

        def holiday_of(session):
            return holidays.filtered(lambda h: h.date_from <= session.start_datetime <= h.date_to)[:1]

        return api_response({
            'sessions': [{
                'id': s.id,
                'subject': s.subject_id.display_name,
                'teacher': s.faculty_id.display_name,
                'classroom': s.classroom_id.display_name,
                'day': s.days,
                'start_datetime': fields.Datetime.to_string(s.start_datetime),
                'end_datetime': fields.Datetime.to_string(s.end_datetime),
                'state': s.state,
                # The timetable greys out a holiday's periods ("Thu 12 Holiday").
                'is_holiday': bool(holiday_of(s)),
            } for s in sessions],
            'holidays': [{
                'id': h.id, 'name': h.name,
                'date_from': fields.Datetime.to_string(h.date_from),
                'date_to': fields.Datetime.to_string(h.date_to),
            } for h in holidays],
        })

    @http.route('/api/v1/parent/timetable/export', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def timetable_export(self, student_id=None, date_from=None, date_to=None, **kwargs):
        """The Timetable screen's "Export Schedule": the same periods as an
        iCalendar (.ics) file a phone calendar can import. Default range:
        the next 7 days; at most 120 days. Holiday periods are left out."""
        student, error = _get_authorized_student(student_id)
        if error:
            return error
        try:
            date_from_val = fields.Datetime.from_string(date_from) if date_from else fields.Datetime.now()
            date_to_val = fields.Datetime.from_string(date_to) if date_to else date_from_val + timedelta(days=7)
        except ValueError:
            return api_error('date_from/date_to must be dates.', status=400, code='invalid_date')
        if date_to_val - date_from_val > timedelta(days=120):
            return api_error('Export at most 120 days at a time.', status=400, code='range_too_long')
        sessions = request.env['op.session'].sudo().search(_sessions_domain(student) + [
            ('start_datetime', '>=', date_from_val), ('start_datetime', '<=', date_to_val),
            ('state', '!=', 'cancel')], order='start_datetime asc')
        holidays = _holidays(request.env, date_from_val, date_to_val)
        stamp = fields.Datetime.now().strftime('%Y%m%dT%H%M%SZ')
        lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Orbix//Timetable//EN', 'CALSCALE:GREGORIAN',
                 'X-WR-CALNAME:%s' % _ics_escape('Timetable - %s' % student.name)]
        for session in sessions:
            if holidays.filtered(lambda h: h.date_from <= session.start_datetime <= h.date_to):
                continue
            lines += [
                'BEGIN:VEVENT',
                'UID:orbix-session-%s@%s' % (session.id, request.httprequest.host),
                'DTSTAMP:%s' % stamp,
                'DTSTART:%s' % session.start_datetime.strftime('%Y%m%dT%H%M%SZ'),
                'DTEND:%s' % session.end_datetime.strftime('%Y%m%dT%H%M%SZ'),
                'SUMMARY:%s' % _ics_escape(session.subject_id.name or 'Class'),
                'DESCRIPTION:%s' % _ics_escape(session.faculty_id.name or ''),
                'LOCATION:%s' % _ics_escape(session.classroom_id.name or ''),
                'END:VEVENT',
            ]
        lines.append('END:VCALENDAR')
        return api_file_response(('\r\n'.join(lines) + '\r\n').encode(), 'timetable.ics', 'text/calendar')

    @http.route('/api/v1/parent/dashboard', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def dashboard(self, student_id=None, **kwargs):
        student, error = _get_authorized_student(student_id)
        if error:
            return error

        today = fields.Date.today()
        attendance = student._summarize_attendance_rows(
            student._get_attendance_rows(today - timedelta(days=30), today))

        now = fields.Datetime.now()
        upcoming_sessions = request.env['op.session'].sudo().search(_sessions_domain(student) + [
            ('start_datetime', '>=', now),
            ('state', '!=', 'cancel'),
        ], order='start_datetime asc', limit=5)

        latest_result = request.env['op.marksheet.line'].sudo().search([
            ('student_id', '=', student.id),
            ('marksheet_reg_id.state', '=', 'validated'),
        ], order='generated_date desc', limit=1)

        return api_response({
            'student': {
                'id': student.id,
                'name': student.name,
            },
            'fee_summary': student.get_fee_payment_summary(),
            'attendance_last_30_days': {
                'total': attendance['total'],
                'present': attendance['present'],
                'attendance_percentage': attendance['percentage'],
            },
            'upcoming_sessions': [{
                'id': s.id,
                'subject': s.subject_id.display_name,
                'start_datetime': fields.Datetime.to_string(s.start_datetime),
            } for s in upcoming_sessions],
            'latest_exam_result': {
                'percentage': latest_result.percentage,
                'grade': latest_result.grade,
                'status': latest_result.status,
            } if latest_result else None,
        })
