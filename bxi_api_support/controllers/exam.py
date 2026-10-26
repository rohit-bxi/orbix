# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Offline exams (openeducat_exam): the family's date sheet, hall ticket and
report card; exam staff/teachers' schedule changes, marks entry and result
publication."""
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import (
    api_error, api_file_response, api_response, call_action, parse_int, require_auth,
)

from .common import date_str, get_viewable_student, parse_pagination, ref, running_enrollment, school_context

EXAM_STAFF_GROUPS = (
    'openeducat_exam.group_op_exam_user',
    'openeducat_exam.group_op_exam_admin',
    'bxi_academic_management.group_academic_coordinator',
    'bxi_academic_management.group_academic_manager',
)
FAMILY_SESSION_STATES = ('schedule', 'held', 'done')
SESSION_ACTIONS = {
    'schedule': ('act_schedule', ('draft',)),
    'held': ('act_held', ('schedule',)),
    'done': ('act_done', ('held',)),
    'cancel': ('act_cancel', ('draft', 'schedule')),
    'reset-to-draft': ('act_draft', ('cancel',)),
}
EXAM_ACTIONS = {
    'schedule': ('act_schedule', ('draft',)),
    'held': ('act_held', ('schedule',)),
    'result-updated': ('act_result_updated', ('held',)),
    'done': ('act_done', ('result_updated',)),
    'cancel': ('act_cancel', ('draft', 'schedule')),
    'reset-to-draft': ('act_draft', ('cancel',)),
}


def _is_exam_staff(user):
    return any(user.has_group(group) for group in EXAM_STAFF_GROUPS)


def _teaches_exam(env, exam):
    context = school_context(env)
    return bool(context['faculty']) and (
        context['faculty'] in exam.responsible_id or exam.batch_id in context['teaching_batches'])


def _exam_dict(exam, student=None):
    data = {
        'id': exam.id,
        'name': exam.name,
        'exam_code': exam.exam_code,
        'subject': ref(exam.subject_id),
        'start_time': date_str(exam.start_time),
        'end_time': date_str(exam.end_time),
        'total_marks': exam.total_marks,
        'passing_marks': exam.min_marks,
        'state': exam.state,
    }
    if student:
        attendee = exam.attendees_line.filtered(lambda a: a.student_id == student)[:1]
        data['room'] = ref(attendee.room_id)
    return data


def _session_dict(session, student=None):
    return {
        'id': session.id,
        'name': session.name,
        'exam_code': session.exam_code,
        'class': ref(session.course_id),
        'section': ref(session.batch_id),
        'exam_type': ref(session.exam_type),
        'start_date': date_str(session.start_date),
        'end_date': date_str(session.end_date),
        'venue': ref(session.venue),
        'state': session.state,
        'hall_ticket_available': session.state == 'schedule',
        'exams': [_exam_dict(e, student) for e in session.exam_ids.sorted('start_time')],
    }


def _student_sessions_domain(student):
    enrollment = running_enrollment(student)
    if not enrollment:
        return [('id', '=', False)]
    return [('course_id', '=', enrollment.course_id.id), ('state', 'in', FAMILY_SESSION_STATES),
            '|', ('batch_id', '=', False), ('batch_id', '=', enrollment.batch_id.id)]


def _render_pdf(report_ref, records, filename, data=None):
    pdf, _report_type = request.env['ir.actions.report'].sudo()._render_qweb_pdf(report_ref, records.ids, data=data)
    return api_file_response(pdf, filename)


class BxiApiSupportExamController(http.Controller):

    # -- family ---------------------------------------------------------------

    @http.route('/api/v1/exams/schedule', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def schedule(self, student_id=None, **kwargs):
        """The student's date sheet: scheduled/held/done exam sessions of
        their current class with each paper's time and room."""
        student, error = get_viewable_student(request.env, student_id)
        if error:
            return error
        sessions = request.env['op.exam.session'].sudo().search(
            _student_sessions_domain(student), order='start_date desc')
        return api_response({'sessions': [_session_dict(s, student) for s in sessions]})

    @http.route('/api/v1/exams/hall-ticket', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def hall_ticket(self, student_id=None, session_id=None, **kwargs):
        student, error = get_viewable_student(request.env, student_id)
        if error:
            return error
        session_id, error = parse_int(session_id, 'session_id')
        if error:
            return error
        session = request.env['op.exam.session'].sudo().search(
            [('id', '=', session_id)] + _student_sessions_domain(student), limit=1)
        if not session:
            return api_error('Exam session not found.', status=404, code='not_found')
        if session.state != 'schedule':
            return api_error('Hall tickets are only available while the exam is scheduled.',
                             status=400, code='not_available')
        return _render_pdf('bxi_api_support.action_report_hall_ticket_single', session,
                           f'hall-ticket-{session.exam_code}-{student.id}.pdf', data={'student_id': student.id})

    @http.route('/api/v1/exams/report-card/<int:marksheet_line_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def report_card(self, marksheet_line_id, **kwargs):
        """PDF marksheet for one published result (ids come from
        /parent/exam-results)."""
        line = request.env['op.marksheet.line'].sudo().browse(marksheet_line_id)
        if not line.exists() or line.marksheet_reg_id.state != 'validated':
            return api_error('Report card not found.', status=404, code='not_found')
        _student, error = get_viewable_student(request.env, line.student_id.id)
        if error:
            return error
        return _render_pdf('openeducat_exam.report_marksheet', line, f'report-card-{line.id}.pdf')

    # -- staff / teacher ------------------------------------------------------

    @http.route('/api/v1/exams/sessions', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_sessions(self, state=None, **kwargs):
        """Exam staff: all sessions. Teachers: sessions of classes they
        teach."""
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        if _is_exam_staff(request.env.user):
            domain = []
        else:
            context = school_context(request.env)
            if not context['faculty']:
                return api_error('Not authorized to list exam sessions.', status=403, code='forbidden')
            domain = [('course_id', 'in', context['teaching_courses'].ids)]
        if state:
            domain.append(('state', '=', state))
        Session = request.env['op.exam.session'].sudo()
        total = Session.search_count(domain)
        sessions = Session.search(domain, limit=limit, offset=offset, order='start_date desc')
        return api_response({'sessions': [_session_dict(s) for s in sessions]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/exams/sessions/<int:session_id>/<any("schedule", "held", "done", "cancel", "reset-to-draft"):action>',
                type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def session_transition(self, session_id, action, **kwargs):
        if not _is_exam_staff(request.env.user):
            return api_error('Only exam staff can change an exam session.', status=403, code='forbidden')
        session = request.env['op.exam.session'].sudo().browse(session_id)
        if not session.exists():
            return api_error('Exam session not found.', status=404, code='not_found')
        method, allowed_from = SESSION_ACTIONS[action]
        if session.state not in allowed_from:
            return api_error(f"Can't {action} a session that is {session.state}.", status=400, code='invalid_transition')
        _, error = call_action(session, method)
        if error:
            return error
        return api_response(_session_dict(session))

    @http.route('/api/v1/exams/<int:exam_id>/<any("schedule", "held", "result-updated", "done", "cancel", "reset-to-draft"):action>',
                type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def exam_transition(self, exam_id, action, **kwargs):
        if not _is_exam_staff(request.env.user):
            return api_error('Only exam staff can change an exam.', status=403, code='forbidden')
        exam = request.env['op.exam'].sudo().browse(exam_id)
        if not exam.exists():
            return api_error('Exam not found.', status=404, code='not_found')
        method, allowed_from = EXAM_ACTIONS[action]
        if exam.state not in allowed_from:
            return api_error(f"Can't {action} an exam that is {exam.state}.", status=400, code='invalid_transition')
        _, error = call_action(exam, method)
        if error:
            return error
        return api_response(_exam_dict(exam))

    @http.route('/api/v1/exams/<int:exam_id>/attendees', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def attendees(self, exam_id, **kwargs):
        exam = request.env['op.exam'].sudo().browse(exam_id)
        if not exam.exists():
            return api_error('Exam not found.', status=404, code='not_found')
        if not (_is_exam_staff(request.env.user) or _teaches_exam(request.env, exam)):
            return api_error('Not authorized for this exam.', status=403, code='forbidden')
        return api_response({
            'exam': _exam_dict(exam),
            'attendees': [{
                'id': a.id,
                'student': ref(a.student_id),
                'roll_number': running_enrollment(a.student_id).roll_number or None,
                'status': a.status,
                'marks': a.marks,
                'note': a.note or None,
                'room': ref(a.room_id),
            } for a in exam.attendees_line],
        })

    @http.route('/api/v1/exams/<int:exam_id>/marks', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def enter_marks(self, exam_id, **kwargs):
        """Bulk marks entry: {"marks": [{"student_id", "marks", "status"?,
        "note"?}]}. All rows are validated before anything is saved."""
        exam = request.env['op.exam'].sudo().browse(exam_id)
        if not exam.exists():
            return api_error('Exam not found.', status=404, code='not_found')
        if not (_is_exam_staff(request.env.user) or _teaches_exam(request.env, exam)):
            return api_error('Not authorized for this exam.', status=403, code='forbidden')
        if exam.state not in ('held', 'result_updated'):
            return api_error('Marks can be entered once the exam is held.', status=400, code='invalid_transition')
        entries = (request.get_json_data() or {}).get('marks') or []
        if not entries:
            return api_error('marks is required.', status=400, code='missing_marks')
        attendee_by_student = {a.student_id.id: a for a in exam.attendees_line}
        updates = []
        for entry in entries:
            student_id, error = parse_int(entry.get('student_id'), 'student_id')
            if error:
                return error
            attendee = attendee_by_student.get(student_id)
            if not attendee:
                return api_error(f'Student {student_id} is not an attendee of this exam.', status=400, code='not_attendee')
            status = entry.get('status', 'present')
            if status not in ('present', 'absent'):
                return api_error('status must be present or absent.', status=400, code='invalid_status')
            marks, error = parse_int(entry.get('marks', 0) if status == 'present' else 0, 'marks')
            if error:
                return error
            if not 0 <= marks <= exam.total_marks:
                return api_error(f'Marks must be between 0 and {exam.total_marks}.', status=400, code='invalid_marks')
            vals = {'marks': marks, 'status': status}
            if 'note' in entry:
                vals['note'] = entry['note'] or False
            updates.append((attendee, vals))
        for attendee, vals in updates:
            attendee.write(vals)
        return self.attendees(exam_id)

    @http.route('/api/v1/exams/result-templates/<int:template_id>/generate', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def generate_results(self, template_id, **kwargs):
        if not _is_exam_staff(request.env.user):
            return api_error('Only exam staff can generate results.', status=403, code='forbidden')
        template = request.env['op.result.template'].sudo().browse(template_id)
        if not template.exists():
            return api_error('Result template not found.', status=404, code='not_found')
        if template.state != 'draft':
            return api_error('Results were already generated for this template.', status=400, code='invalid_transition')
        _, error = call_action(template, 'generate_result')
        if error:
            return error
        register = request.env['op.marksheet.register'].sudo().search(
            [('result_template_id', '=', template.id)], order='id desc', limit=1)
        return api_response({'marksheet_register_id': register.id, 'state': register.state}, status=201)

    @http.route('/api/v1/exams/marksheets/<int:register_id>/publish', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def publish_marksheet(self, register_id, **kwargs):
        """Validate a marksheet register - its results then show in the
        family's /parent/exam-results and report cards."""
        if not _is_exam_staff(request.env.user):
            return api_error('Only exam staff can publish results.', status=403, code='forbidden')
        register = request.env['op.marksheet.register'].sudo().browse(register_id)
        if not register.exists():
            return api_error('Marksheet not found.', status=404, code='not_found')
        if register.state != 'draft':
            return api_error('Only a draft marksheet can be published.', status=400, code='invalid_transition')
        _, error = call_action(register, 'action_validate')
        if error:
            return error
        return api_response({'id': register.id, 'state': register.state, 'students': len(register.marksheet_line)})
