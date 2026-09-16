# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import calendar as calendar_module

from odoo import fields, http
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.exceptions import MissingError
from odoo.http import request

# Marksheet lines are only shown to the student once the register has been
# validated by staff - a draft register is provisional/ungraded data that
# shouldn't leak to a portal user before publication.
MARKSHEET_PUBLISHED_STATE = 'validated'
ASSIGNMENT_VISIBLE_STATES = ('publish', 'finish')

# Shared visual vocabulary for the dashboard-style pages: attendance status
# to bootstrap color, and a color cycle for anything grouped by subject
# (there's no subject->color field anywhere in openeducat, so this is the
# only stable way to keep the same subject in the same color across cards).
ATTENDANCE_STATUS_COLOR = {'present': 'success', 'absent': 'danger', 'late': 'warning', 'excused': 'secondary'}
SUBJECT_COLOR_CYCLE = ['primary', 'success', 'info', 'warning', 'danger', 'secondary']
WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def _grade_from_percentage(pct):
    if pct >= 90:
        return 'A+'
    if pct >= 80:
        return 'A'
    if pct >= 70:
        return 'B+'
    if pct >= 60:
        return 'B'
    if pct >= 50:
        return 'C'
    if pct >= 35:
        return 'D'
    return 'F'


class StudentPortal(CustomerPortal):

    # ------------------------------------------------------------------
    # Access resolution - shared by every route below and reused as-is by
    # bxi_parent_portal (which passes the child's student_id explicitly).
    # ------------------------------------------------------------------
    def _resolve_target_student(self, student_id=None):
        """Return the op.student the current user is allowed to view.

        With no student_id, resolves to "the logged-in student themself".
        With a student_id, relies entirely on ir.rule (student_parent_login_rule
        in openeducat_parent: self or one of the caller's children) - this
        method never uses sudo() for the actual access check, only to tell
        a genuinely missing record apart from an access-denied one.
        """
        Student = request.env['op.student']
        if student_id:
            student = Student.browse(int(student_id))
            if not student.sudo().exists():
                raise MissingError("This student record does not exist.")
            student.check_access('read')
            return student.sudo()
        student = Student.sudo().search([('user_id', '=', request.env.uid)], limit=1)
        if not student:
            raise MissingError("No student profile is linked to this account.")
        return student

    # ------------------------------------------------------------------
    # Aggregation helpers - kept here (not on the model) since they only
    # ever back a portal page and would otherwise add cross-module fields
    # to op.student for a purely presentational need.
    # ------------------------------------------------------------------
    def _attendance_summary(self, student):
        lines = request.env['op.attendance.line'].search([
            ('student_id', '=', student.id),
            ('state', '=', 'done'),
        ])
        total = len(lines)
        present = len(lines.filtered('present'))
        return {
            'total': total,
            'present': present,
            'absent': len(lines.filtered('absent')),
            'late': len(lines.filtered('late')),
            'excused': len(lines.filtered('excused')),
            'percentage': round((present / total) * 100, 1) if total else 0.0,
        }

    def _upcoming_sessions(self, student, limit=5):
        now = fields.Datetime.now()
        return request.env['op.session'].search([
            ('student_ids', 'in', student.id),
            ('start_datetime', '>=', now),
        ], order='start_datetime asc', limit=limit)

    def _pending_assignment_count(self, student):
        return request.env['op.assignment'].search_count([
            ('allocation_ids', 'in', student.id),
            ('state', 'in', ASSIGNMENT_VISIBLE_STATES),
            ('submission_date', '>=', fields.Datetime.now()),
        ])

    def _fees_due_total(self, student):
        details = request.env['op.student.fees.details'].search([
            ('student_id', '=', student.id),
            ('invoice_state', 'in', ('draft', 'posted')),
        ])
        return sum(details.mapped('invoice_id.amount_residual'))

    # ------------------------------------------------------------------
    # Dashboard aggregations - calendar/grid/report-card views built on
    # top of the same recordsets the plain list pages already fetch, kept
    # here rather than on the models since they're purely presentational.
    # ------------------------------------------------------------------
    def _attendance_calendar(self, lines):
        """Bucket attendance lines onto a Sun-Sat month grid for the most
        recent recorded month (falls back to the current month when the
        student has no attendance yet)."""
        status_by_date = {}
        for line in lines:
            if line.present:
                status_by_date[line.attendance_date] = 'present'
            elif line.absent:
                status_by_date[line.attendance_date] = 'absent'
            elif line.late:
                status_by_date[line.attendance_date] = 'late'
            elif line.excused:
                status_by_date[line.attendance_date] = 'excused'
        ref_date = max(status_by_date) if status_by_date else fields.Date.today()
        cal = calendar_module.Calendar(firstweekday=6)  # weeks start on Sunday
        weeks = []
        for week in cal.monthdatescalendar(ref_date.year, ref_date.month):
            weeks.append([{
                'day': day.day,
                'in_month': day.month == ref_date.month,
                'status': status_by_date.get(day),
                'color': ATTENDANCE_STATUS_COLOR.get(status_by_date.get(day)),
            } for day in week])
        return {'month_label': ref_date.strftime('%B %Y'), 'weeks': weeks}

    def _attendance_subject_breakdown(self, lines):
        """Present/total per subject (via the attendance register), sorted
        best-attendance-first, each tagged with a stable subject color.

        Portal users have no direct read access to op.attendance.register
        (it's staff-only, unlike op.attendance.line which carries its own
        student-scoped ir.rule) - sudo() is safe here because `lines` is
        already the access-checked, student-scoped recordset; we're only
        reading the register's subject name off of it, not exposing any
        other student's data.
        """
        buckets = {}
        for line in lines:
            subject = line.sudo().register_id.subject_id
            key = subject.id
            entry = buckets.setdefault(key, {'subject': subject.name or 'General', 'present': 0, 'total': 0})
            entry['total'] += 1
            if line.present:
                entry['present'] += 1
        result = []
        for i, entry in enumerate(buckets.values()):
            entry['percentage'] = round(entry['present'] * 100.0 / entry['total'], 0) if entry['total'] else 0.0
            entry['color'] = SUBJECT_COLOR_CYCLE[i % len(SUBJECT_COLOR_CYCLE)]
            result.append(entry)
        return sorted(result, key=lambda r: -r['percentage'])

    def _timetable_grid(self, sessions):
        """Pivot dated sessions onto a Mon-Sun x time-slot weekly pattern,
        the way a school timetable is normally displayed. When two sessions
        land on the same weekday/slot (e.g. two different weeks), the most
        recent one wins the cell."""
        slots = sorted({s.start_datetime.strftime('%H:%M') for s in sessions})
        grid = {slot: {day: None for day in WEEKDAY_LABELS} for slot in slots}
        for session in sessions.sorted('start_datetime'):
            day = WEEKDAY_LABELS[session.start_datetime.weekday()]
            slot = session.start_datetime.strftime('%H:%M')
            grid[slot][day] = session
        subjects = sessions.mapped('subject_id')
        subject_colors = {subj.id: SUBJECT_COLOR_CYCLE[i % len(SUBJECT_COLOR_CYCLE)] for i, subj in enumerate(subjects)}
        return {'slots': slots, 'days': WEEKDAY_LABELS, 'grid': grid, 'subject_colors': subject_colors}

    def _exam_subject_performance(self, student):
        """Average percentage per subject across every result line the
        student has, each tagged with a computed letter grade and color."""
        result_lines = request.env['op.result.line'].search([('student_id', '=', student.id)])
        buckets = {}
        for rl in result_lines:
            subject = rl.exam_id.subject_id
            key = subject.id
            total_marks = rl.exam_id.total_marks or 100
            entry = buckets.setdefault(key, {'subject': subject.name or 'General', 'scores': []})
            entry['scores'].append(rl.marks * 100.0 / total_marks)
        result = []
        for i, entry in enumerate(buckets.values()):
            pct = round(sum(entry['scores']) / len(entry['scores']), 1) if entry['scores'] else 0.0
            result.append({
                'subject': entry['subject'],
                'percentage': pct,
                'grade': _grade_from_percentage(pct),
                'exams_count': len(entry['scores']),
                'color': SUBJECT_COLOR_CYCLE[i % len(SUBJECT_COLOR_CYCLE)],
            })
        return sorted(result, key=lambda r: -r['percentage'])

    # ------------------------------------------------------------------
    # Portal home tile
    # ------------------------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        student = request.env['op.student'].sudo().search(
            [('user_id', '=', request.env.uid)], limit=1)
        if student:
            values['academics_student'] = student
            values['academics_attendance'] = self._attendance_summary(student)
            values['academics_upcoming'] = self._upcoming_sessions(student, limit=1)
            values['academics_pending_assignments'] = self._pending_assignment_count(student)
            values['academics_fees_due'] = self._fees_due_total(student)
        return values

    # ------------------------------------------------------------------
    # Routes - each accepts an optional student_id so bxi_parent_portal can
    # link straight into these same pages for a specific child.
    # ------------------------------------------------------------------
    @http.route(['/my/academics', '/my/academics/<int:student_id>'],
                type='http', auth='user', website=True)
    def portal_academics_home(self, student_id=None, **kw):
        student = self._resolve_target_student(student_id)
        return request.render('bxi_student_portal.portal_academics_home', {
            'student': student,
            'attendance': self._attendance_summary(student),
            'upcoming_sessions': self._upcoming_sessions(student),
            'pending_assignments': self._pending_assignment_count(student),
            'fees_due': self._fees_due_total(student),
            'page_name': 'academics',
            'student_id': student_id,
        })

    @http.route(['/my/academics/attendance', '/my/academics/<int:student_id>/attendance'],
                type='http', auth='user', website=True)
    def portal_academics_attendance(self, student_id=None, date_from=None, date_to=None, **kw):
        student = self._resolve_target_student(student_id)
        domain = [('student_id', '=', student.id), ('state', '=', 'done')]
        if date_from:
            domain.append(('attendance_date', '>=', date_from))
        if date_to:
            domain.append(('attendance_date', '<=', date_to))
        lines = request.env['op.attendance.line'].search(domain, order='attendance_date desc')
        return request.render('bxi_student_portal.portal_academics_attendance', {
            'student': student,
            'lines': lines,
            'summary': self._attendance_summary(student),
            'calendar': self._attendance_calendar(lines),
            'subject_breakdown': self._attendance_subject_breakdown(lines),
            'date_from': date_from,
            'date_to': date_to,
            'page_name': 'academics',
            'student_id': student_id,
        })

    @http.route(['/my/academics/timetable', '/my/academics/<int:student_id>/timetable'],
                type='http', auth='user', website=True)
    def portal_academics_timetable(self, student_id=None, **kw):
        student = self._resolve_target_student(student_id)
        sessions = request.env['op.session'].search(
            [('student_ids', 'in', student.id)], order='start_datetime asc')
        return request.render('bxi_student_portal.portal_academics_timetable', {
            'student': student,
            'sessions': sessions,
            'timetable_grid': self._timetable_grid(sessions),
            'page_name': 'academics',
            'student_id': student_id,
        })

    @http.route(['/my/academics/exams', '/my/academics/<int:student_id>/exams'],
                type='http', auth='user', website=True)
    def portal_academics_exams(self, student_id=None, **kw):
        student = self._resolve_target_student(student_id)
        marksheets = request.env['op.marksheet.line'].search([
            ('student_id', '=', student.id),
            ('marksheet_reg_id.state', '=', MARKSHEET_PUBLISHED_STATE),
        ], order='generated_date desc')
        passed_count = len(marksheets.filtered(lambda ms: ms.status == 'pass'))
        overall_percentage = round(sum(marksheets.mapped('percentage')) / len(marksheets), 1) if marksheets else 0.0
        return request.render('bxi_student_portal.portal_academics_exams', {
            'student': student,
            'marksheets': marksheets,
            'passed_count': passed_count,
            'overall_percentage': overall_percentage,
            'subject_performance': self._exam_subject_performance(student),
            'page_name': 'academics',
            'student_id': student_id,
        })

    @http.route(['/my/academics/assignments', '/my/academics/<int:student_id>/assignments'],
                type='http', auth='user', website=True)
    def portal_academics_assignments(self, student_id=None, **kw):
        student = self._resolve_target_student(student_id)
        assignments = request.env['op.assignment'].search([
            ('allocation_ids', 'in', student.id),
            ('state', 'in', ASSIGNMENT_VISIBLE_STATES),
        ], order='submission_date desc')
        submissions = request.env['op.assignment.sub.line'].search([
            ('student_id', '=', student.id),
            ('assignment_id', 'in', assignments.ids),
        ])
        submission_by_assignment = {sub.assignment_id.id: sub for sub in submissions}
        return request.render('bxi_student_portal.portal_academics_assignments', {
            'student': student,
            'assignments': assignments,
            'submission_by_assignment': submission_by_assignment,
            'page_name': 'academics',
            'student_id': student_id,
        })

    @http.route(['/my/academics/library', '/my/academics/<int:student_id>/library'],
                type='http', auth='user', website=True)
    def portal_academics_library(self, student_id=None, **kw):
        student = self._resolve_target_student(student_id)
        movements = request.env['op.media.movement'].search(
            [('student_id', '=', student.id)], order='issued_date desc')
        today = fields.Date.today()
        return request.render('bxi_student_portal.portal_academics_library', {
            'student': student,
            'movements': movements,
            'today': today,
            'page_name': 'academics',
            'student_id': student_id,
        })

    @http.route(['/my/academics/fees', '/my/academics/<int:student_id>/fees'],
                type='http', auth='user', website=True)
    def portal_academics_fees(self, student_id=None, **kw):
        student = self._resolve_target_student(student_id)
        details = request.env['op.student.fees.details'].search(
            [('student_id', '=', student.id)], order='date desc')
        return request.render('bxi_student_portal.portal_academics_fees', {
            'student': student,
            'details': details,
            'due_total': self._fees_due_total(student),
            'page_name': 'academics',
            'student_id': student_id,
        })
