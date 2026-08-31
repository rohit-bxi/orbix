# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import fields
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth


def _user_can_access_student(env, student):
    """Same rule as the other parent-facing modules: staff (any regular
    backend user) or a parent linked to the student.
    """
    user = env.user
    if user.has_group('base.group_user'):
        return True
    return bool(env['op.parent'].sudo().search_count([
        ('user_id', '=', user.id), ('student_ids', 'in', student.id),
    ]))


def _get_authorized_student(payload_student_id):
    if not payload_student_id:
        return None, api_error('student_id is required.', status=400, code='missing_student_id')
    student = request.env['op.student'].sudo().browse(int(payload_student_id))
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

        lines = request.env['op.attendance.line'].sudo().search([
            ('student_id', '=', student.id),
            ('attendance_date', '>=', date_from_val),
            ('attendance_date', '<=', date_to_val),
        ], order='attendance_date desc')

        present_count = len(lines.filtered('present'))
        absent_count = len(lines.filtered('absent'))
        late_count = len(lines.filtered('late'))
        excused_count = len(lines.filtered('excused'))
        total = len(lines)

        return api_response({
            'summary': {
                'total': total,
                'present': present_count,
                'absent': absent_count,
                'late': late_count,
                'excused': excused_count,
                'attendance_percentage': round(100.0 * present_count / total, 1) if total else 0.0,
            },
            'records': [{
                'date': fields.Date.to_string(line.attendance_date),
                'present': line.present,
                'absent': line.absent,
                'late': line.late,
                'excused': line.excused,
                'remark': line.remark,
            } for line in lines],
        })

    @http.route('/api/v1/parent/timetable', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def timetable(self, student_id=None, date_from=None, date_to=None, **kwargs):
        student, error = _get_authorized_student(student_id)
        if error:
            return error

        date_from_val = fields.Datetime.from_string(date_from) if date_from else fields.Datetime.now()
        date_to_val = fields.Datetime.from_string(date_to) if date_to else date_from_val + timedelta(days=7)

        sessions = request.env['op.session'].sudo().search([
            ('student_ids', 'in', student.id),
            ('start_datetime', '>=', date_from_val),
            ('start_datetime', '<=', date_to_val),
            ('state', '!=', 'cancel'),
        ], order='start_datetime asc')

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
            } for s in sessions],
        })

    @http.route('/api/v1/parent/dashboard', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def dashboard(self, student_id=None, **kwargs):
        student, error = _get_authorized_student(student_id)
        if error:
            return error

        today = fields.Date.today()
        thirty_days_ago = today - timedelta(days=30)
        attendance_lines = request.env['op.attendance.line'].sudo().search([
            ('student_id', '=', student.id),
            ('attendance_date', '>=', thirty_days_ago),
            ('attendance_date', '<=', today),
        ])
        present_count = len(attendance_lines.filtered('present'))
        total_attendance = len(attendance_lines)

        now = fields.Datetime.now()
        upcoming_sessions = request.env['op.session'].sudo().search([
            ('student_ids', 'in', student.id),
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
                'total': total_attendance,
                'present': present_count,
                'attendance_percentage': round(100.0 * present_count / total_attendance, 1) if total_attendance else 0.0,
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
