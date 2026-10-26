# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth

from .common import get_viewable_student, session_students

# Same three groups bxi_student_attendance's own ir.rule domains already use
# to widen visibility on hr.attendance for student rows.
COORDINATOR_GROUP = 'bxi_academic_management.group_academic_coordinator'
MANAGER_GROUP = 'bxi_academic_management.group_academic_manager'
FACULTY_GROUP = 'openeducat_core.group_op_faculty'


def _is_coordinator_or_manager(user):
    return user.has_group(COORDINATOR_GROUP) or user.has_group(MANAGER_GROUP)


def _is_attendance_staff(user):
    return _is_coordinator_or_manager(user) or user.has_group(FACULTY_GROUP)


def _session_owned_by(user, session):
    return _is_coordinator_or_manager(user) or session.faculty_id.user_id.id == user.id


def _attendance_dict(attendance):
    return {
        'id': attendance.id,
        'student_id': attendance.student_id.id,
        'session_id': attendance.session_id.id or None,
        'class': attendance.class_id.display_name,
        'section': attendance.section_id.display_name,
        'status': attendance.status,
        'check_in': attendance.check_in and fields.Datetime.to_string(attendance.check_in),
        'check_out': attendance.check_out and fields.Datetime.to_string(attendance.check_out),
        'remark': attendance.remark,
    }


class BxiApiSupportAttendanceController(http.Controller):

    @http.route('/api/v1/attendance/checkin', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def checkin(self, **kwargs):
        if not _is_attendance_staff(request.env.user):
            return api_error('Not authorized to mark attendance.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        student_id = payload.get('student_id')
        if not student_id:
            return api_error('student_id is required.', status=400, code='missing_student_id')
        student_id, error = parse_int(student_id, 'student_id')
        if error:
            return error
        student = request.env['op.student'].sudo().browse(student_id)
        if not student.exists():
            return api_error('Student not found.', status=404, code='not_found')
        if not student.employee_id:
            return api_error('Student has no attendance record set up.', status=400, code='no_employee')

        check_in = payload.get('check_in') or fields.Datetime.to_string(fields.Datetime.now())
        attendance = request.env['hr.attendance'].sudo().create({
            'employee_id': student.employee_id.id,
            'check_in': check_in,
        })
        return api_response(_attendance_dict(attendance), status=201)

    @http.route('/api/v1/attendance/checkout/<int:attendance_id>', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def checkout(self, attendance_id, **kwargs):
        if not _is_attendance_staff(request.env.user):
            return api_error('Not authorized to mark attendance.', status=403, code='forbidden')
        attendance = request.env['hr.attendance'].sudo().browse(attendance_id)
        if not attendance.exists() or not attendance.student_id:
            return api_error('Attendance record not found.', status=404, code='not_found')
        if attendance.session_id and not _session_owned_by(request.env.user, attendance.session_id):
            return api_error('Not authorized for this attendance record.', status=403, code='forbidden')
        if attendance.check_out:
            return api_error('This attendance record already has a check-out time.', status=400, code='already_checked_out')

        payload = request.get_json_data() or {}
        check_out = payload.get('check_out') or fields.Datetime.to_string(fields.Datetime.now())
        attendance.check_out = check_out
        return api_response(_attendance_dict(attendance))

    @http.route('/api/v1/attendance/mark', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def mark(self, **kwargs):
        """Teacher-entered correction (absent/late/excused) for a student on
        a specific period, without a real kiosk/badge check-in - the same
        manual-entry case the underlying hr.attendance override on
        bxi_student_attendance documents.
        """
        if not _is_attendance_staff(request.env.user):
            return api_error('Not authorized to mark attendance.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        status = payload.get('status')
        if status not in ('present', 'absent', 'late', 'excused'):
            return api_error(
                'status must be one of present, absent, late, excused.', status=400, code='invalid_status')

        if not payload.get('student_id'):
            return api_error('student_id is required.', status=400, code='missing_student_id')
        if not payload.get('session_id'):
            return api_error('session_id is required.', status=400, code='missing_session_id')
        student_id, error = parse_int(payload['student_id'], 'student_id')
        if error:
            return error
        session_id, error = parse_int(payload['session_id'], 'session_id')
        if error:
            return error

        student = request.env['op.student'].sudo().browse(student_id)
        session = request.env['op.session'].sudo().browse(session_id)
        if not student.exists() or not session.exists():
            return api_error('Student or session not found.', status=404, code='not_found')
        if not student.employee_id:
            return api_error('Student has no attendance record set up.', status=400, code='no_employee')
        if not _session_owned_by(request.env.user, session):
            return api_error('Not authorized for this session.', status=403, code='forbidden')

        Attendance = request.env['hr.attendance'].sudo()
        existing = Attendance.search([('student_id', '=', student.id), ('session_id', '=', session.id)], limit=1)
        vals = {'status': status, 'remark': payload.get('remark')}
        if existing:
            existing.write(vals)
            attendance = existing
        else:
            vals.update({'employee_id': student.employee_id.id, 'session_id': session.id})
            attendance = Attendance.create(vals)
        return api_response(_attendance_dict(attendance))

    @http.route('/api/v1/attendance/sessions/<int:session_id>/roster', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def roster(self, session_id, **kwargs):
        if not _is_attendance_staff(request.env.user):
            return api_error('Not authorized to view attendance rosters.', status=403, code='forbidden')
        session = request.env['op.session'].sudo().browse(session_id)
        if not session.exists():
            return api_error('Session not found.', status=404, code='not_found')
        if not _session_owned_by(request.env.user, session):
            return api_error('Not authorized for this session.', status=403, code='forbidden')

        attendance_by_student = {
            a.student_id.id: a
            for a in request.env['hr.attendance'].sudo().search([('session_id', '=', session.id)])
        }
        roster = []
        for student in session_students(session):
            attendance = attendance_by_student.get(student.id)
            roster.append({
                'student_id': student.id,
                'student_name': student.name,
                'attendance_id': attendance.id if attendance else None,
                'status': attendance.status if attendance else None,
                'check_in': attendance.check_in and fields.Datetime.to_string(attendance.check_in) if attendance else None,
                'check_out': attendance.check_out and fields.Datetime.to_string(attendance.check_out) if attendance else None,
            })
        return api_response({
            'session': {
                'id': session.id,
                'subject': session.subject_id.display_name,
                'start_datetime': session.start_datetime and fields.Datetime.to_string(session.start_datetime),
                'end_datetime': session.end_datetime and fields.Datetime.to_string(session.end_datetime),
            },
            'roster': roster,
        })

    @http.route('/api/v1/attendance/sessions/<int:session_id>/bulk-mark', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def bulk_mark(self, session_id, **kwargs):
        """Mark a whole period in one call: {"marks": [{"student_id",
        "status", "remark"?}]}. Every row is validated first; then all are
        saved together (updating any existing mark for that student and
        period), so a bad row never leaves the register half-marked."""
        if not _is_attendance_staff(request.env.user):
            return api_error('Not authorized to mark attendance.', status=403, code='forbidden')
        session = request.env['op.session'].sudo().browse(session_id)
        if not session.exists():
            return api_error('Session not found.', status=404, code='not_found')
        if not _session_owned_by(request.env.user, session):
            return api_error('Not authorized for this session.', status=403, code='forbidden')
        entries = (request.get_json_data() or {}).get('marks') or []
        if not entries:
            return api_error('marks is required.', status=400, code='missing_marks')

        roster = {s.id: s for s in session_students(session)}
        rows = []
        for entry in entries:
            student_id, error = parse_int(entry.get('student_id'), 'student_id')
            if error:
                return error
            student = roster.get(student_id)
            if not student:
                return api_error(f'Student {student_id} is not on this period\'s roster.', status=400, code='not_on_roster')
            if entry.get('status') not in ('present', 'absent', 'late', 'excused'):
                return api_error(
                    'status must be one of present, absent, late, excused.', status=400, code='invalid_status')
            if not student.employee_id:
                student._ensure_attendance_employee()
            rows.append((student, entry['status'], entry.get('remark')))

        Attendance = request.env['hr.attendance'].sudo()
        existing = {a.student_id.id: a for a in Attendance.search([
            ('session_id', '=', session.id), ('student_id', 'in', [s.id for s, _st, _r in rows]),
        ])}
        create_vals = []
        for student, status, remark in rows:
            vals = {'status': status, 'remark': remark or False}
            if student.id in existing:
                existing[student.id].write(vals)
            else:
                create_vals.append(dict(vals, employee_id=student.employee_id.id, session_id=session.id))
        Attendance.create(create_vals)
        return self.roster(session_id)

    @http.route('/api/v1/attendance/students/<int:student_id>/summary', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def student_summary(self, student_id, date_from=None, date_to=None, **kwargs):
        """Same numbers the parent app shows, for a teacher/coordinator:
        counts, percentage, per-day roll-up and the period rows."""
        student, error = get_viewable_student(request.env, student_id)
        if error:
            return error
        try:
            start = fields.Date.to_date(date_from) if date_from else None
            end = fields.Date.to_date(date_to) if date_to else None
        except ValueError:
            return api_error('date_from/date_to must be YYYY-MM-DD.', status=400, code='invalid_date')
        rows = student._get_attendance_rows(start, end)
        summary = student._summarize_attendance_rows(rows)
        return api_response({
            'student_id': student.id,
            'summary': {k: summary[k] for k in ('total', 'present', 'absent', 'late', 'excused', 'percentage')},
            'days': [dict(d, date=fields.Date.to_string(d['date'])) for d in summary['days']],
            'records': [dict(r, date=fields.Date.to_string(r['date']),
                             start_datetime=r['start_datetime'] and fields.Datetime.to_string(r['start_datetime']),
                             check_in=r['check_in'] and fields.Datetime.to_string(r['check_in']),
                             check_out=r['check_out'] and fields.Datetime.to_string(r['check_out']))
                        for r in rows],
        })
