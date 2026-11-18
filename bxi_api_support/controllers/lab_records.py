# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Lab attendance and experiment results (op_student_lab_management): the
instructor marks who came and enters each student's marks for the
session's experiment; families read a student's lab results."""
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth

from .common import atomic, date_str, get_viewable_student, parse_pagination, ref, json_body
from .lab import _is_lab_admin

ATTENDANCE_STATES = ('confirmed', 'in_progress', 'done')
RESULT_STATES = ('in_progress', 'done')
ATTENDANCE_STATUSES = ('present', 'absent', 'late')


def _roster(session):
    """The session's students, or - when none were picked - everyone
    currently in its section."""
    if session.student_ids:
        return session.student_ids
    return session.env['op.student.course'].sudo().search(
        [('batch_id', '=', session.batch_id.id), ('state', '=', 'running')]).student_id


def _session_ref(session):
    return {
        'id': session.id,
        'name': session.name,
        'date': date_str(session.date),
        'state': session.state,
        'room': ref(session.room_id),
        'class': ref(session.course_id),
        'section': ref(session.batch_id),
        'subject': ref(session.subject_id),
        'experiment': ref(session.experiment_id),
        'instructor': ref(session.faculty_id),
    }


def _result_dict(result):
    return {
        'id': result.id,
        'student': ref(result.student_id),
        'experiment': ref(result.experiment_id),
        'max_marks': result.max_marks,
        'marks_obtained': result.marks_obtained,
        'grade': result.grade or None,
        'remark': result.remark or None,
    }


def _parse_rows(payload, key, roster):
    """(rows, None) or (None, api_error) for a list of per-student entries,
    every student checked against the session roster."""
    rows = payload.get(key)
    if not isinstance(rows, list) or not rows:
        return None, api_error(f'{key} is required.', status=400, code=f'missing_{key}')
    seen = set()
    for row in rows:
        student_id, error = parse_int((row or {}).get('student_id'), 'student_id')
        if error:
            return None, error
        if student_id not in roster.ids:
            return None, api_error(f'Student {student_id} is not in this lab session.', status=400,
                                   code='not_in_session')
        if student_id in seen:
            return None, api_error(f'Student {student_id} is listed twice.', status=400, code='duplicate_student')
        seen.add(student_id)
        row['student_id'] = student_id
    return rows, None


class BxiApiSupportLabRecordsController(http.Controller):

    def _session(self, session_id):
        """Same rule as lab.py's session routes: lab admins, or the
        session's instructor."""
        session = request.env['lab.session'].sudo().browse(session_id)
        if not session.exists():
            return None, api_error('Lab session not found.', status=404, code='not_found')
        user = request.env.user
        if _is_lab_admin(user) or session.faculty_id.user_id == user:
            return session, None
        return None, api_error('Not authorized for this session.', status=403, code='forbidden')

    # -- attendance ----------------------------------------------------------------

    @http.route('/api/v1/lab/sessions/<int:session_id>/attendance', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_attendance(self, session_id, **kwargs):
        session, error = self._session(session_id)
        if error:
            return error
        marks = {a.student_id.id: a for a in session.attendance_ids}
        roster = _roster(session)
        return api_response({
            'session': _session_ref(session),
            'students': [{
                'student': ref(student),
                'status': marks[student.id].status if student.id in marks else None,
                'remark': marks[student.id].remark or None if student.id in marks else None,
            } for student in roster.sorted('name')],
            'summary': {status: len([a for a in marks.values() if a.status == status])
                        for status in ATTENDANCE_STATUSES} | {'unmarked': len(roster.filtered(lambda s: s.id not in marks))},
        })

    @http.route('/api/v1/lab/sessions/<int:session_id>/attendance', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def mark_attendance(self, session_id, **kwargs):
        """{"records": [{"student_id", "status": present|absent|late,
        "remark"?}]} - once the session is confirmed. Saves all or none."""
        session, error = self._session(session_id)
        if error:
            return error
        if session.state not in ATTENDANCE_STATES:
            return api_error('Attendance can be marked once the session is confirmed.', status=400,
                             code='invalid_state')
        rows, error = _parse_rows(json_body() or {}, 'records', _roster(session))
        if error:
            return error
        for row in rows:
            if row.get('status', 'present') not in ATTENDANCE_STATUSES:
                return api_error('status must be one of present, absent, late.', status=400, code='invalid_status')
        existing = {a.student_id.id: a for a in session.attendance_ids}

        def save():
            for row in rows:
                vals = {'status': row.get('status', 'present')}
                if 'remark' in row:
                    vals['remark'] = row['remark'] or False
                if row['student_id'] in existing:
                    existing[row['student_id']].write(vals)
                else:
                    request.env['lab.attendance'].sudo().create(
                        dict(vals, session_id=session.id, student_id=row['student_id']))

        _, error = atomic(save)
        if error:
            return error
        return self.get_attendance(session_id)

    # -- experiment results ------------------------------------------------------

    def _experiment(self, session, value):
        if value in (None, ''):
            if not session.experiment_id:
                return None, api_error('experiment_id is required: this session has no experiment.',
                                       status=400, code='missing_experiment_id')
            return session.experiment_id, None
        experiment_id, error = parse_int(value, 'experiment_id')
        if error:
            return None, error
        experiment = request.env['lab.experiment'].sudo().browse(experiment_id).exists()
        if not experiment:
            return None, api_error('Experiment not found.', status=404, code='not_found')
        return experiment, None

    @http.route('/api/v1/lab/sessions/<int:session_id>/results', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_results(self, session_id, experiment_id=None, **kwargs):
        session, error = self._session(session_id)
        if error:
            return error
        domain = [('session_id', '=', session.id)]
        if experiment_id:
            experiment, error = self._experiment(session, experiment_id)
            if error:
                return error
            domain.append(('experiment_id', '=', experiment.id))
        results = request.env['lab.experiment.result'].sudo().search(domain)
        return api_response({
            'session': _session_ref(session),
            'results': [_result_dict(r) for r in results.sorted(lambda r: r.student_id.name or '')],
        })

    @http.route('/api/v1/lab/sessions/<int:session_id>/results', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def enter_results(self, session_id, **kwargs):
        """{"experiment_id"? (default: the session's), "results":
        [{"student_id", "marks_obtained", "remark"?}]} - once the session
        has started. Marks run from 0 to the experiment's maximum."""
        session, error = self._session(session_id)
        if error:
            return error
        if session.state not in RESULT_STATES:
            return api_error('Results can be entered once the session has started.', status=400,
                             code='invalid_state')
        payload = json_body() or {}
        experiment, error = self._experiment(session, payload.get('experiment_id'))
        if error:
            return error
        rows, error = _parse_rows(payload, 'results', _roster(session))
        if error:
            return error
        for row in rows:
            try:
                row['marks_obtained'] = float(row.get('marks_obtained'))
            except (TypeError, ValueError):
                return api_error('marks_obtained must be a number.', status=400, code='invalid_marks')
            if row['marks_obtained'] < 0 or (experiment.max_marks and row['marks_obtained'] > experiment.max_marks):
                return api_error(f'marks_obtained must be between 0 and {experiment.max_marks:g}.', status=400,
                                 code='invalid_marks')
        Result = request.env['lab.experiment.result'].sudo()
        existing = {r.student_id.id: r for r in Result.search(
            [('session_id', '=', session.id), ('experiment_id', '=', experiment.id)])}

        def save():
            for row in rows:
                vals = {'marks_obtained': row['marks_obtained']}
                if 'remark' in row:
                    vals['remark'] = row['remark'] or False
                if row['student_id'] in existing:
                    existing[row['student_id']].write(vals)
                else:
                    Result.create(dict(vals, session_id=session.id, experiment_id=experiment.id,
                                       student_id=row['student_id']))

        _, error = atomic(save)
        if error:
            return error
        return self.get_results(session_id, experiment_id=str(experiment.id))

    # -- family ------------------------------------------------------------------

    @http.route('/api/v1/lab/results', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def student_results(self, student_id=None, **kwargs):
        """A student's lab record (the student, their parents and teachers):
        experiment results plus lab attendance, newest first."""
        student, error = get_viewable_student(request.env, student_id)
        if error:
            return error
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Result = request.env['lab.experiment.result'].sudo()
        domain = [('student_id', '=', student.id)]
        results = Result.search(domain, limit=limit, offset=offset, order='id desc')
        attendance = request.env['lab.attendance'].sudo().search([('student_id', '=', student.id)])
        return api_response({
            'student': ref(student),
            'attendance': {status: len(attendance.filtered(lambda a, s=status: a.status == s))
                           for status in ATTENDANCE_STATUSES},
            'results': [dict(_result_dict(r), session=_session_ref(r.session_id)) for r in results],
        }, meta={'total': Result.search_count(domain), 'limit': limit, 'offset': offset})
