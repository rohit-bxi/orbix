# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tools.misc import format_datetime

_logger = logging.getLogger(__name__)


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    # Only rows created for absence/lateness bookkeeping (no real scan
    # happened) go through this model without a check_in; standard
    # kiosk/systray/badge check-ins always supply one via the base flow.
    check_in = fields.Datetime(required=False)

    student_id = fields.Many2one(
        'op.student', string='Student', related='employee_id.student_id',
        store=True, index=True)
    class_id = fields.Many2one(
        'op.course', string='Class', compute='_compute_class_section',
        store=True, index=True)
    section_id = fields.Many2one(
        'op.batch', string='Section', compute='_compute_class_section',
        store=True, index=True)
    session_id = fields.Many2one(
        'op.session', string='Period', ondelete='cascade', index=True)
    status = fields.Selection([
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('excused', 'Excused'),
    ], string='Attendance Status')
    remark = fields.Char('Comment')

    _unique_student_session = models.Constraint(
        'unique(student_id, session_id)',
        'Attendance for this student on this period already exists.')

    @api.depends('student_id', 'student_id.course_detail_ids.state')
    def _compute_class_section(self):
        for attendance in self:
            enrollment = attendance.student_id.course_detail_ids.filtered(
                lambda line: line.state == 'running')[:1]
            attendance.class_id = enrollment.course_id
            attendance.section_id = enrollment.batch_id

    @api.constrains('check_in', 'check_out', 'employee_id')
    def _check_validity(self):
        """A student's hand-marked row is an instant (check_in ==
        check_out == the moment it was marked) - bookkeeping, not a stay.
        hr_attendance's overlap check compares the row with "the latest
        record before check_in" and "... before check_out" found by two
        searches ordered on check_in alone: when the student has several
        rows stamped in the same second (marking periods one after
        another), the two can pick different rows of that tie and refuse a
        valid mark. So an instant student row is only refused when a real
        stay (e.g. a kiosk check-in) spans it; every other row keeps the
        standard check."""
        instants = self.filtered(lambda a: a.employee_id.student_id and a.check_in and a.check_in == a.check_out)
        super(HrAttendance, self - instants)._check_validity()
        for attendance in instants:
            spanning = self.sudo().search([
                ('employee_id', '=', attendance.employee_id.id), ('id', '!=', attendance.id),
                ('check_in', '<', attendance.check_in), ('check_out', '>', attendance.check_in)], limit=1)
            if spanning:
                raise ValidationError(self.env._(
                    'Cannot create new attendance record for %(name)s, the employee was already checked in on '
                    '%(datetime)s', name=attendance.employee_id.name,
                    datetime=format_datetime(self.env, spanning.check_in, dt_format=False)))

    # A mark's attendance date is its period's date - not check_in, which
    # for a hand-marked row is the moment the teacher marked it. Only a row
    # without a dated period falls back to check_in, read in the user's
    # timezone. _attendance_date() and _date_range_domain() both apply this
    # rule, so per-student screens and school-wide lists count the same.

    def _attendance_date(self):
        """This row's attendance date, or None when it has neither a dated
        period nor a check-in."""
        self.ensure_one()
        if self.session_id.session_date:
            return self.session_id.session_date
        if self.check_in:
            return fields.Datetime.context_timestamp(self, self.check_in).date()
        return None

    @api.model
    def _date_range_domain(self, date_from=None, date_to=None):
        """Rows whose _attendance_date() falls between the two dates
        (inclusive; either may be None), as an exact database domain."""
        if not (date_from or date_to):
            return Domain.TRUE
        dated = Domain('session_id.session_date', '!=', False)
        undated = Domain('session_id', '=', False) | Domain('session_id.session_date', '=', False)
        if date_from:
            dated &= Domain('session_id.session_date', '>=', date_from)
            undated &= Domain('check_in', '>=', self._local_midnight_utc(date_from))
        if date_to:
            dated &= Domain('session_id.session_date', '<=', date_to)
            undated &= Domain('check_in', '<', self._local_midnight_utc(date_to + timedelta(days=1)))
        return dated | undated

    @api.model
    def _local_midnight_utc(self, day):
        """The start of `day` in the user's timezone, as a naive UTC datetime."""
        local = self.env.tz.localize(datetime.combine(day, time.min))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    def _find_matching_session(self, student, check_in):
        """The op.session whose class window a check-in at `check_in` falls
        into, for `student`'s currently running enrollment - or an empty
        recordset if there's no running enrollment or no session covers
        that moment (e.g. no class scheduled that day/period).

        This is what lets the teacher-visibility security rule
        (session_id.faculty_id.user_id) actually match real check-ins:
        without it, kiosk/systray/badge scans never set session_id at all
        and that rule silently matches nothing for any teacher.
        """
        if not (student and check_in):
            return self.env['op.session']
        enrollment = student.course_detail_ids.filtered(lambda line: line.state == 'running')[:1]
        if not enrollment:
            return self.env['op.session']
        sessions = self.env['op.session'].sudo().search([
            ('course_id', '=', enrollment.course_id.id),
            ('batch_id', '=', enrollment.batch_id.id),
            ('session_date', '=', check_in.date()),
        ])
        return sessions.filtered(
            lambda s: s.start_datetime and s.end_datetime and s.start_datetime <= check_in <= s.end_datetime)[:1]

    @api.model_create_multi
    def create(self, vals_list):
        # A row created with a real check_in but no explicit status came
        # through the standard flow (kiosk/systray/badge) for a student
        # shadow employee — that scan itself means "present". Rows a
        # teacher enters by hand for absence/lateness always pass
        # `status` explicitly and are left untouched.
        employee_ids = {vals['employee_id'] for vals in vals_list if vals.get('employee_id')}
        student_employees = self.env['hr.employee']
        if employee_ids:
            # .exists() first: a stale/invalid device-supplied employee_id must fall through to
            # the normal FK validation in super().create() with a clean error, not crash here.
            student_employees = self.env['hr.employee'].browse(employee_ids).exists().filtered('student_id')
        student_employee_map = {employee.id: employee for employee in student_employees}
        for vals in vals_list:
            employee = student_employee_map.get(vals.get('employee_id'))
            if not employee:
                continue
            is_manual_entry = 'status' in vals
            if not is_manual_entry:
                vals['status'] = 'present'
            if not vals.get('session_id') and vals.get('check_in'):
                check_in = fields.Datetime.to_datetime(vals['check_in'])
                session = self._find_matching_session(employee.student_id, check_in)
                if session:
                    vals['session_id'] = session.id
            if is_manual_entry and not vals.get('check_in') and not vals.get('check_out'):
                # A teacher-entered bookkeeping row (absent/present/late marked by
                # hand, no real scan) has no natural check-out event either. Base
                # hr.attendance treats any record without check_out as "open" and
                # refuses to create a second one for the same employee - which
                # would otherwise mean the FIRST manual entry ever created for a
                # student permanently blocks every later attendance (manual or
                # real check-in) for them. Stamp it as an instantaneous, already
                # "closed" record instead so it does not linger open.
                now = fields.Datetime.now()
                vals['check_in'] = now
                vals['check_out'] = now
        return super().create(vals_list)

    @api.model
    def _copy_legacy_op_attendance(self, domain=None):
        """One-time copy of OpenEduCat attendance sheets (op.attendance.line)
        into hr.attendance, now the only attendance store the portal and
        the app read. A line is skipped when hr.attendance already has a
        row for that student and period (hr.attendance wins), when it has
        no status ticked, or when it would overlap another of the student's
        records (e.g. a kiosk check-in spanning that period). Each copied
        row is an instant at the period start, the same way teacher-marked
        rows are stamped, so it doesn't block later check-ins.
        `domain` narrows which op.attendance.line rows are copied (all of
        them by default, as the install and migration hooks want).
        Returns (copied, skipped, conflicts).
        """
        if 'op.attendance.line' not in self.env:
            return 0, 0, 0
        lines = self.env['op.attendance.line'].sudo().with_context(active_test=False).search(
            [('attendance_id.state', '!=', 'cancel')] + list(domain or []), order='attendance_date, id')
        existing = {
            (a.student_id.id, a.session_id.id)
            for a in self.sudo().search([('student_id', '!=', False), ('session_id', '!=', False)])
        }
        # A line without a period has nothing to match on but the student,
        # its instant, status and remark: those keep a rerun from copying it
        # twice, while different marks on the same day are all kept.
        existing_undated = {
            (a.student_id.id, a.check_in, a.status, a.remark or False)
            for a in self.sudo().search([('student_id', '!=', False), ('session_id', '=', False)])
        }
        # History, not news: modules that notify families on an absence
        # (bxi_api_support) skip rows created under this flag.
        Attendance = self.sudo().with_context(bxi_no_notify=True)
        copied = skipped = conflicts = 0
        for line in lines:
            student = line.student_id
            session = line.attendance_id.session_id
            status = next((s for s in ('present', 'absent', 'late', 'excused') if line[s]), None)
            if not student or not status or (session and (student.id, session.id) in existing):
                skipped += 1
                continue
            if session.start_datetime:
                stamp = session.start_datetime
            elif line.attendance_date:
                stamp = datetime.combine(line.attendance_date, time(0))
            else:
                skipped += 1
                continue
            undated_key = (student.id, stamp, status, line.remark or False)
            if not session and undated_key in existing_undated:
                skipped += 1
                continue
            student._ensure_attendance_employee()
            try:
                with self.env.cr.savepoint():
                    Attendance.create({
                        'employee_id': student.employee_id.id,
                        'session_id': session.id or False,
                        'status': status,
                        'remark': line.remark or False,
                        'check_in': stamp,
                        'check_out': stamp,
                    })
            except ValidationError:
                conflicts += 1
                continue
            if session:
                existing.add((student.id, session.id))
            else:
                existing_undated.add(undated_key)
            copied += 1
        _logger.info(
            'Copied %s OpenEduCat attendance lines into hr.attendance (%s skipped, %s overlapping).',
            copied, skipped, conflicts)
        return copied, skipped, conflicts
