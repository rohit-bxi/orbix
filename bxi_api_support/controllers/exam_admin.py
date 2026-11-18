# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Offline exam set-up (openeducat_exam) for exam staff: creating an exam
session with its papers, editing them while still in draft, seating
students (attendees and rooms), and the result templates and marksheet
registers that exam.py's generate/publish routes act on."""
from odoo import http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth

from .common import (
    atomic, check_selection, date_str, parse_date, parse_datetime, parse_pagination, ref, resolve_record,
    resolve_records, running_enrollment, school_context,
)
from .exam import _exam_dict, _is_exam_staff, _session_dict

EXAM_CODE_MAX = 16
# Rooms and students are only (re)assigned before the paper is sat.
SEATING_STATES = ('draft', 'schedule')
# A room is free unless another paper still to be sat overlaps it.
ROOM_BUSY_STATES = ('schedule', 'held')


def _forbidden(message='Only exam staff can set up exams.'):
    return api_error(message, status=403, code='forbidden')


def _required(payload, keys):
    for key in keys:
        if payload.get(key) in (None, '', False):
            return api_error(f'{key} is required.', status=400, code=f'missing_{key}')
    return None


def _code_taken(model, code, record=None):
    domain = [('exam_code', '=', code)] + ([('id', '!=', record.id)] if record else [])
    return bool(request.env[model].sudo().with_context(active_test=False).search_count(domain))


def _session_vals(env, payload, session=None):
    """(vals, error) for an op.exam.session create/write."""
    vals = {}
    if 'name' in payload:
        if not payload['name']:
            return None, api_error('name cannot be empty.', status=400, code='missing_name')
        vals['name'] = payload['name']
    if 'exam_code' in payload:
        code = str(payload['exam_code'] or '').strip()
        if not code:
            return None, api_error('exam_code cannot be empty.', status=400, code='missing_exam_code')
        if _code_taken('op.exam.session', code, session):
            return None, api_error(f"Exam code '{code}' is already used.", status=400, code='duplicate_exam_code')
        vals['exam_code'] = code
    for key in ('start_date', 'end_date'):
        if key in payload:
            vals[key], error = parse_date(payload[key], key)
            if error or not vals[key]:
                return None, error or api_error(f'{key} is required.', status=400, code=f'missing_{key}')
    for key, model, field in (('class_id', 'op.course', 'course_id'), ('section_id', 'op.batch', 'batch_id'),
                              ('exam_type_id', 'op.exam.type', 'exam_type')):
        if key in payload:
            record, error = resolve_record(env, model, payload[key], key)
            if error:
                return None, error
            if not record:
                return None, api_error(f'{key} is required.', status=400, code=f'missing_{key}')
            vals[field] = record.id
    if 'venue_id' in payload:
        venue, error = resolve_record(env, 'res.partner', payload['venue_id'], 'venue_id')
        if error:
            return None, error
        vals['venue'] = venue.id or False
    if 'evaluation_type' in payload:
        error = check_selection(env['op.exam.session'], 'evaluation_type', payload['evaluation_type'])
        if error:
            return None, error
        vals['evaluation_type'] = payload['evaluation_type']
    course = env['op.course'].sudo().browse(vals.get('course_id')) if 'course_id' in vals else (session.course_id if session else None)
    batch = env['op.batch'].sudo().browse(vals.get('batch_id')) if 'batch_id' in vals else (session.batch_id if session else None)
    if course and batch and batch.course_id != course:
        return None, api_error('This section does not belong to that class.', status=400, code='batch_course_mismatch')
    start = vals.get('start_date') or (session.start_date if session else None)
    end = vals.get('end_date') or (session.end_date if session else None)
    if start and end and end < start:
        return None, api_error('end_date cannot be before start_date.', status=400, code='invalid_dates')
    return vals, None


def _exam_vals(env, payload, session, exam=None):
    """(vals, error) for an op.exam create/write inside `session`. A paper's
    subject must be one of the class's subjects (when the class lists
    any); a missing code is made from the session code and subject code."""
    vals = {}
    if 'subject_id' in payload:
        subject, error = resolve_record(env, 'op.subject', payload['subject_id'], 'subject_id')
        if error:
            return None, error
        if not subject:
            return None, api_error('subject_id is required.', status=400, code='missing_subject_id')
        if session.course_id.subject_ids and subject not in session.course_id.subject_ids:
            return None, api_error(f'{subject.name} is not a subject of {session.course_id.name}.',
                                   status=400, code='subject_not_in_class')
        vals['subject_id'] = subject.id
    if 'name' in payload:
        if not payload['name']:
            return None, api_error('name cannot be empty.', status=400, code='missing_name')
        vals['name'] = payload['name']
    if 'exam_code' in payload:
        code = str(payload['exam_code'] or '').strip()
        if not code:
            return None, api_error('exam_code cannot be empty.', status=400, code='missing_exam_code')
        vals['exam_code'] = code
    for key in ('start_time', 'end_time'):
        if key in payload:
            vals[key], error = parse_datetime(payload[key], key)
            if error or not vals[key]:
                return None, error or api_error(f'{key} is required.', status=400, code=f'missing_{key}')
    marks_keys = (('total_marks', 'total_marks'), ('passing_marks', 'min_marks'), ('min_marks', 'min_marks'))
    for key, field in marks_keys:
        if key in payload:
            value, error = parse_int(payload[key], key)
            if error:
                return None, error
            vals[field] = value
    if 'note' in payload:
        vals['note'] = payload['note'] or False
    if 'responsible_ids' in payload:
        teachers, error = resolve_records(env, 'op.faculty', payload['responsible_ids'], 'responsible_ids')
        if error:
            return None, error
        vals['responsible_id'] = [(6, 0, teachers.ids)]
    if not exam:
        subject = env['op.subject'].sudo().browse(vals.get('subject_id'))
        vals.setdefault('name', f'{subject.name} - {session.name}')
        if 'exam_code' not in vals:
            vals['exam_code'] = _free_exam_code(f'{session.exam_code}-{subject.code or subject.id}')
    if vals.get('exam_code'):
        if len(vals['exam_code']) > EXAM_CODE_MAX:
            return None, api_error(f'exam_code can be at most {EXAM_CODE_MAX} characters.', status=400,
                                   code='invalid_exam_code')
        if _code_taken('op.exam', vals['exam_code'], exam):
            return None, api_error(f"Exam code '{vals['exam_code']}' is already used.", status=400,
                                   code='duplicate_exam_code')
    return vals, None


def _free_exam_code(base):
    """`base` cut to the column size, numbered until no paper uses it."""
    code = base[:EXAM_CODE_MAX]
    counter = 2
    while _code_taken('op.exam', code):
        suffix = f'-{counter}'
        code = base[:EXAM_CODE_MAX - len(suffix)] + suffix
        counter += 1
    return code


def _default_attendees(env, exam):
    """Who sits a paper when the office doesn't list students: everyone
    currently in the session's section (or class), and for an elective
    only the students whose subject registration includes it."""
    session = exam.session_id
    domain = [('state', '=', 'running'), ('course_id', '=', session.course_id.id)]
    if session.batch_id:
        domain.append(('batch_id', '=', session.batch_id.id))
    students = env['op.student.course'].sudo().search(domain).student_id
    if exam.subject_id.subject_type == 'elective':
        registered = env['op.subject.registration'].sudo().search([
            ('student_id', 'in', students.ids), ('state', '=', 'approved'),
            ('elective_subject_ids', 'in', exam.subject_id.id),
        ]).student_id
        students &= registered
    return students


def _attendee_dict(attendee):
    return {
        'id': attendee.id,
        'student': ref(attendee.student_id),
        'roll_number': running_enrollment(attendee.student_id).roll_number or None,
        'room': ref(attendee.room_id),
        'status': attendee.status,
    }


def _grade_dict(grade):
    return {'id': grade.id, 'result': grade.result, 'min_percentage': grade.min_per,
            'max_percentage': grade.max_per}


def _template_dict(template):
    register = template.env['op.marksheet.register'].sudo().search(
        [('result_template_id', '=', template.id)], order='id desc', limit=1)
    return {
        'id': template.id,
        'name': template.name,
        'exam_session': ref(template.exam_session_id),
        'evaluation_type': template.evaluation_type,
        'result_date': date_str(template.result_date),
        'grades': [_grade_dict(g) for g in template.grade_ids.sorted('min_per')],
        'state': template.state,
        'marksheet_register_id': register.id or None,
    }


def _register_dict(register, lines=False):
    data = {
        'id': register.id,
        'name': register.name,
        'exam_session': ref(register.exam_session_id),
        'result_template': ref(register.result_template_id),
        'generated_date': date_str(register.generated_date),
        'generated_by': ref(register.generated_by),
        'state': register.state,
        'students': len(register.marksheet_line),
        'total_pass': register.total_pass,
        'total_failed': register.total_failed,
    }
    if lines:
        data['lines'] = [{
            'id': line.id,
            'student': ref(line.student_id),
            'total_marks': line.total_marks,
            'percentage': line.percentage,
            'grade': line.grade or None,
            'status': line.status,
            'subjects': [{'exam': ref(r.exam_id), 'marks': r.marks, 'grade': r.grade or None,
                          'status': r.status} for r in line.result_line],
        } for line in register.marksheet_line.sorted(lambda l: l.student_id.name or '')]
    return data


class BxiApiSupportExamAdminController(http.Controller):

    def _session(self, session_id):
        session = request.env['op.exam.session'].sudo().browse(session_id)
        if not session.exists():
            return None, api_error('Exam session not found.', status=404, code='not_found')
        return session, None

    def _exam(self, exam_id):
        exam = request.env['op.exam'].sudo().browse(exam_id)
        if not exam.exists():
            return None, api_error('Exam not found.', status=404, code='not_found')
        return exam, None

    # -- sessions and papers --------------------------------------------------

    @http.route('/api/v1/exams/sessions', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_session(self, **kwargs):
        """{"name", "exam_code", "class_id", "section_id", "exam_type_id",
        "start_date", "end_date", "evaluation_type"?, "venue_id"?,
        "exams"?: [{"subject_id", "start_time", "end_time", "total_marks",
        "passing_marks", "name"?, "exam_code"?, "responsible_ids"?, "note"?}]}
        - the session and its papers are saved together or not at all."""
        env = request.env
        if not _is_exam_staff(env.user):
            return _forbidden()
        payload = request.get_json_data() or {}
        error = _required(payload, ('name', 'exam_code', 'class_id', 'section_id', 'exam_type_id',
                                    'start_date', 'end_date'))
        if error:
            return error
        vals, error = _session_vals(env, payload)
        if error:
            return error
        exams = payload.get('exams') or []
        if not isinstance(exams, list):
            return api_error('exams must be a list.', status=400, code='invalid_exams')

        def create():
            session = env['op.exam.session'].sudo().create(vals)
            for index, entry in enumerate(exams):
                missing = _required(entry or {}, ('subject_id', 'start_time', 'end_time', 'total_marks',
                                                  'passing_marks'))
                if missing:
                    raise _PayloadError(missing)
                exam_vals, problem = _exam_vals(env, entry, session)
                if problem:
                    raise _PayloadError(problem)
                env['op.exam'].sudo().create(dict(exam_vals, session_id=session.id))
            return session

        try:
            session, error = atomic(create)
        except _PayloadError as exc:
            return exc.response
        if error:
            return error
        return api_response(_session_dict(session), status=201)

    @http.route('/api/v1/exams/sessions/<int:session_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_session(self, session_id, **kwargs):
        """Exam staff, or a teacher of the session's class."""
        env = request.env
        session, error = self._session(session_id)
        if error:
            return error
        if not _is_exam_staff(env.user) and session.course_id not in school_context(env)['teaching_courses']:
            return _forbidden('Not authorized for this exam session.')
        data = _session_dict(session)
        data['evaluation_type'] = session.evaluation_type
        for exam_data, exam in zip(data['exams'], session.exam_ids.sorted('start_time')):
            exam_data.update(attendee_count=len(exam.attendees_line), results_entered=exam.results_entered,
                             responsible=[ref(t) for t in exam.responsible_id], note=exam.note or None)
        templates = env['op.result.template'].sudo().search([('exam_session_id', '=', session.id)])
        data['result_templates'] = [_template_dict(t) for t in templates]
        return api_response(data)

    @http.route('/api/v1/exams/sessions/<int:session_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_session(self, session_id, **kwargs):
        """Any create field except exams; only while the session is draft."""
        env = request.env
        if not _is_exam_staff(env.user):
            return _forbidden()
        session, error = self._session(session_id)
        if error:
            return error
        if session.state != 'draft':
            return api_error('Only a draft exam session can be edited.', status=400, code='invalid_state')
        vals, error = _session_vals(env, request.get_json_data() or {}, session)
        if error:
            return error
        _, error = atomic(lambda: session.write(vals))
        if error:
            return error
        return api_response(_session_dict(session))

    @http.route('/api/v1/exams/sessions/<int:session_id>/exams', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def add_exam(self, session_id, **kwargs):
        """Add one paper to a draft or scheduled session (same body as an
        item of the create route's "exams")."""
        env = request.env
        if not _is_exam_staff(env.user):
            return _forbidden()
        session, error = self._session(session_id)
        if error:
            return error
        if session.state not in SEATING_STATES:
            return api_error('Papers can only be added to a draft or scheduled session.', status=400,
                             code='invalid_state')
        payload = request.get_json_data() or {}
        error = _required(payload, ('subject_id', 'start_time', 'end_time', 'total_marks', 'passing_marks'))
        if error:
            return error
        vals, error = _exam_vals(env, payload, session)
        if error:
            return error
        exam, error = atomic(lambda: env['op.exam'].sudo().create(dict(vals, session_id=session.id)))
        if error:
            return error
        return api_response(_exam_dict(exam), status=201)

    @http.route('/api/v1/exams/<int:exam_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_exam(self, exam_id, **kwargs):
        env = request.env
        if not _is_exam_staff(env.user):
            return _forbidden()
        exam, error = self._exam(exam_id)
        if error:
            return error
        if exam.state != 'draft':
            return api_error('Only a draft exam can be edited.', status=400, code='invalid_state')
        vals, error = _exam_vals(env, request.get_json_data() or {}, exam.session_id, exam)
        if error:
            return error
        _, error = atomic(lambda: exam.write(vals))
        if error:
            return error
        return api_response(_exam_dict(exam))

    @http.route('/api/v1/exams/<int:exam_id>/assign-attendees', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def assign_attendees(self, exam_id, **kwargs):
        """{"student_ids"?, "room_ids"?} - who sits the paper and where.
        Without student_ids: the section's current students (for an
        elective, those registered for it). Rooms are filled in the order
        given up to their capacity. Replaces the paper's earlier seating;
        only before the paper is held."""
        env = request.env
        if not _is_exam_staff(env.user):
            return _forbidden()
        exam, error = self._exam(exam_id)
        if error:
            return error
        if exam.state not in SEATING_STATES:
            return api_error('Seating can only change before the exam is held.', status=400, code='invalid_state')
        payload = request.get_json_data() if request.httprequest.get_data() else {}
        payload = payload or {}
        if payload.get('student_ids'):
            students, error = resolve_records(env, 'op.student', payload['student_ids'], 'student_ids')
            if error:
                return error
        else:
            students = _default_attendees(env, exam)
        if not students:
            return api_error('No students to seat for this exam.', status=400, code='no_students')
        rooms, error = resolve_records(env, 'op.exam.room', payload.get('room_ids') or [], 'room_ids')
        if error:
            return error
        if rooms:
            capacity = sum(rooms.mapped('capacity'))
            if capacity < len(students):
                return api_error(f'The rooms seat {capacity} but {len(students)} students sit this exam.',
                                 status=400, code='not_enough_seats')
            busy = env['op.exam.attendees'].sudo().search([
                ('room_id', 'in', rooms.ids), ('exam_id', '!=', exam.id),
                ('exam_id.state', 'in', ROOM_BUSY_STATES),
                ('exam_id.start_time', '<', exam.end_time), ('exam_id.end_time', '>', exam.start_time),
            ]).room_id
            if busy:
                return api_error('Already booked at that time: %s.' % ', '.join(busy.mapped('name')),
                                 status=400, code='room_busy')
        seats = []
        for room in rooms:
            seats += [room.id] * room.capacity

        def seat():
            exam.attendees_line.unlink()
            ordered = students.sorted(lambda s: (running_enrollment(s).roll_number or '', s.name or ''))
            env['op.exam.attendees'].sudo().create([{
                'exam_id': exam.id, 'student_id': student.id,
                'room_id': seats[index] if seats else False,
            } for index, student in enumerate(ordered)])

        _, error = atomic(seat)
        if error:
            return error
        return api_response({'exam': _exam_dict(exam), 'attendees': [_attendee_dict(a) for a in exam.attendees_line]})

    # -- results ---------------------------------------------------------------

    @http.route('/api/v1/exams/result-templates', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_templates(self, session_id=None, state=None, **kwargs):
        if not _is_exam_staff(request.env.user):
            return _forbidden()
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = Domain.TRUE
        if session_id:
            session_id, error = parse_int(session_id, 'session_id')
            if error:
                return error
            domain &= Domain('exam_session_id', '=', session_id)
        if state:
            domain &= Domain('state', '=', state)
        Template = request.env['op.result.template'].sudo()
        templates = Template.search(domain, limit=limit, offset=offset, order='result_date desc, id desc')
        return api_response({'templates': [_template_dict(t) for t in templates]},
                            meta={'total': Template.search_count(domain), 'limit': limit, 'offset': offset})

    @http.route('/api/v1/exams/result-templates', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_template(self, **kwargs):
        """{"exam_session_id", "name"?, "result_date"?, "grade_ids"?} -
        every paper of the session must be done first."""
        env = request.env
        if not _is_exam_staff(env.user):
            return _forbidden()
        payload = request.get_json_data() or {}
        error = _required(payload, ('exam_session_id',))
        if error:
            return error
        session, error = resolve_record(env, 'op.exam.session', payload['exam_session_id'], 'exam_session_id')
        if error:
            return error
        if not session.exam_ids:
            return api_error('This exam session has no exams.', status=400, code='no_exams')
        if session.exam_ids.filtered(lambda e: e.state != 'done'):
            return api_error('Every exam of the session must be done first.', status=400, code='exams_not_done')
        vals = {'exam_session_id': session.id, 'name': payload.get('name') or f'Result - {session.name}'}
        if payload.get('result_date'):
            vals['result_date'], error = parse_date(payload['result_date'], 'result_date')
            if error:
                return error
        if payload.get('grade_ids'):
            grades, error = resolve_records(env, 'op.grade.configuration', payload['grade_ids'], 'grade_ids')
            if error:
                return error
            vals['grade_ids'] = [(6, 0, grades.ids)]
        template, error = atomic(lambda: env['op.result.template'].sudo().create(vals))
        if error:
            return error
        return api_response(_template_dict(template), status=201)

    @http.route('/api/v1/exams/marksheets', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_marksheets(self, session_id=None, state=None, **kwargs):
        if not _is_exam_staff(request.env.user):
            return _forbidden()
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = Domain.TRUE
        if session_id:
            session_id, error = parse_int(session_id, 'session_id')
            if error:
                return error
            domain &= Domain('exam_session_id', '=', session_id)
        if state:
            error = check_selection(request.env['op.marksheet.register'], 'state', state)
            if error:
                return error
            domain &= Domain('state', '=', state)
        Register = request.env['op.marksheet.register'].sudo()
        registers = Register.search(domain, limit=limit, offset=offset, order='generated_date desc, id desc')
        return api_response({'marksheets': [_register_dict(r) for r in registers]},
                            meta={'total': Register.search_count(domain), 'limit': limit, 'offset': offset})

    @http.route('/api/v1/exams/marksheets/<int:register_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_marksheet(self, register_id, **kwargs):
        """The register with one line per student; a line's id is what
        /exams/report-card/<id> takes once the register is published."""
        if not _is_exam_staff(request.env.user):
            return _forbidden()
        register = request.env['op.marksheet.register'].sudo().browse(register_id)
        if not register.exists():
            return api_error('Marksheet not found.', status=404, code='not_found')
        return api_response(_register_dict(register, lines=True))


class _PayloadError(Exception):
    """Carries an api_error out of an atomic() block, so a bad nested
    item rolls back what was already created."""

    def __init__(self, response):
        super().__init__('invalid payload')
        self.response = response
