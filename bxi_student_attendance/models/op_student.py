# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from collections import defaultdict
from datetime import datetime, time, timedelta

from odoo import api, fields, models

ATTENDANCE_STATUSES = ('present', 'absent', 'late', 'excused')


def _day_status(statuses):
    """Roll one day's per-period statuses up into a single status."""
    statuses = set(statuses)
    if statuses == {'absent'}:
        return 'absent'
    if statuses == {'excused'}:
        return 'excused'
    if 'absent' in statuses:
        return 'partial'
    if 'late' in statuses:
        return 'late'
    return 'present'


class OpStudent(models.Model):
    _inherit = 'op.student'

    employee_id = fields.Many2one(
        'hr.employee', string='Attendance Employee', copy=False, readonly=True,
        help='Lightweight shadow employee record used only so this '
             'student can check in/out through the standard Attendances '
             'kiosk/systray/badge flow. Carries no payroll/contract data.')

    @api.model_create_multi
    def create(self, vals_list):
        students = super().create(vals_list)
        students._ensure_attendance_employee()
        return students

    def _get_attendance_rows(self, date_from=None, date_to=None):
        """This student's marked attendance (hr.attendance, the system of
        record), one dict per period, newest first. Shared by the parent
        API, the student/parent portal and the teacher app so all of them
        show the same numbers.

        Reads with sudo(): family logins have no access to hr.attendance at
        all, so callers must already have checked that the user may see
        this student. A row's date is its period's date - not check_in,
        which for a hand-marked row is the moment the teacher marked it.
        Rows with no status (e.g. a staff kiosk scan) are not attendance.
        """
        self.ensure_one()
        domain = [('student_id', '=', self.id), ('status', '!=', False)]
        # Widened by a day on each side for session-less rows, whose local
        # date is only known after the timezone conversion below.
        if date_from:
            domain += ['|', ('session_id.session_date', '>=', date_from), '&', ('session_id', '=', False),
                       ('check_in', '>=', datetime.combine(date_from - timedelta(days=1), time.min))]
        if date_to:
            domain += ['|', ('session_id.session_date', '<=', date_to), '&', ('session_id', '=', False),
                       ('check_in', '<=', datetime.combine(date_to + timedelta(days=1), time.max))]
        rows = []
        for attendance in self.env['hr.attendance'].sudo().search(domain):
            session = attendance.session_id
            if session.session_date:
                day = session.session_date
            elif attendance.check_in:
                day = fields.Datetime.context_timestamp(self, attendance.check_in).date()
            else:
                continue
            if (date_from and day < date_from) or (date_to and day > date_to):
                continue
            rows.append({
                'id': attendance.id,
                'date': day,
                'session_id': session.id or None,
                'period': session.timing_id.display_name if session.timing_id else None,
                'start_datetime': session.start_datetime or None,
                'subject_id': session.subject_id.id or None,
                'subject': session.subject_id.name or None,
                'course': attendance.class_id.name or None,
                'batch': attendance.section_id.name or None,
                'status': attendance.status,
                'remark': attendance.remark or None,
                'check_in': attendance.check_in or None,
                'check_out': attendance.check_out or None,
            })
        rows.sort(key=lambda r: (r['date'], r['start_datetime'] or datetime.min), reverse=True)
        return rows

    @api.model
    def _summarize_attendance_rows(self, rows):
        """Counts, percentage and a per-day roll-up for `rows` from
        _get_attendance_rows. Percentage is present periods / marked
        periods, the same definition the portal has always shown; a day
        mixing absent with other statuses rolls up to 'partial'."""
        counts = {status: 0 for status in ATTENDANCE_STATUSES}
        by_day = defaultdict(list)
        for row in rows:
            counts[row['status']] += 1
            by_day[row['date']].append(row['status'])
        total = len(rows)
        return dict(
            counts,
            total=total,
            percentage=round(100.0 * counts['present'] / total, 1) if total else 0.0,
            days=[{'date': day, 'status': _day_status(statuses), 'periods': len(statuses)}
                  for day, statuses in sorted(by_day.items(), reverse=True)],
        )

    def _ensure_attendance_employee(self):
        """Create the shadow hr.employee backing this student's
        attendance identity, if it doesn't exist yet.

        sudo() because creating an hr.employee record isn't something
        the acting user (e.g. admissions staff creating a student)
        necessarily has rights to do directly, and this is bookkeeping
        the student's own record needs regardless of who created it.
        """
        Employee = self.env['hr.employee'].sudo()
        for student in self:
            if student.employee_id:
                continue
            employee = Employee.create({
                'name': student.name,
                'student_id': student.id,
                'employee_type': 'student',
                'company_id': self.env.company.id,
            })
            student.employee_id = employee.id
