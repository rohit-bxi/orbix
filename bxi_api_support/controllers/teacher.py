# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The teacher app's home: today's periods with attendance progress, the
timetable, the sections taught and their rosters, and the student activity
log (openeducat_activity)."""
from datetime import timedelta

from odoo import fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth

from .common import (
    date_str, get_viewable_student, parse_pagination, ref, running_enrollment, safe_create, school_context,
    session_students,
)

ACTIVITY_MANAGER_GROUPS = ('openeducat_activity.group_activity_manager', 'openeducat_activity.group_activity_user')


def _require_faculty(env):
    faculty = school_context(env)['faculty']
    if not faculty:
        return None, api_error('No teacher profile is linked to this account.', status=403, code='not_a_teacher')
    return faculty, None


def _period_dict(session, marked_count=None):
    data = {
        'id': session.id,
        'date': date_str(session.session_date),
        'start_datetime': date_str(session.start_datetime),
        'end_datetime': date_str(session.end_datetime),
        'period': session.timing_id.display_name if session.timing_id else None,
        'subject': ref(session.subject_id),
        'class': ref(session.course_id),
        'section': ref(session.batch_id),
        'classroom': ref(session.classroom_id),
        'state': session.state,
    }
    if marked_count is not None:
        roster_size = len(session_students(session))
        data['student_count'] = roster_size
        data['attendance_marked'] = marked_count
        data['attendance_complete'] = bool(roster_size) and marked_count >= roster_size
    return data


def _section_students(batch):
    return request.env['op.student.course'].sudo().search([
        ('batch_id', '=', batch.id), ('state', '=', 'running'),
    ], order='roll_number, id').student_id


class BxiApiSupportTeacherController(http.Controller):

    @http.route('/api/v1/teacher/today', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def today(self, **kwargs):
        """Today's periods (materialised from the weekly timetable by
        bxi_student_attendance's cron) with how many students are marked."""
        faculty, error = _require_faculty(request.env)
        if error:
            return error
        today = fields.Date.context_today(faculty)
        sessions = request.env['op.session'].sudo().search([
            ('faculty_id', '=', faculty.id), ('session_date', '=', today), ('state', '!=', 'cancel'),
        ], order='start_datetime')
        marked = {}
        if sessions:
            for attendance in request.env['hr.attendance'].sudo().search([
                ('session_id', 'in', sessions.ids), ('status', '!=', False),
            ]):
                marked[attendance.session_id.id] = marked.get(attendance.session_id.id, 0) + 1
        return api_response({
            'date': date_str(today),
            'periods': [_period_dict(s, marked.get(s.id, 0)) for s in sessions],
        })

    @http.route('/api/v1/teacher/timetable', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def timetable(self, date_from=None, date_to=None, **kwargs):
        faculty, error = _require_faculty(request.env)
        if error:
            return error
        try:
            start = fields.Date.to_date(date_from) if date_from else fields.Date.context_today(faculty)
            end = fields.Date.to_date(date_to) if date_to else start + timedelta(days=6)
        except ValueError:
            return api_error('date_from/date_to must be YYYY-MM-DD.', status=400, code='invalid_date')
        sessions = request.env['op.session'].sudo().search([
            ('faculty_id', '=', faculty.id), ('session_date', '>=', start), ('session_date', '<=', end),
            ('state', '!=', 'cancel'),
        ], order='start_datetime')
        weekly = request.env['bxi.timetable.line'].sudo().search([('teacher_id', '=', faculty.id)])
        return api_response({
            'date_from': date_str(start),
            'date_to': date_str(end),
            'periods': [_period_dict(s) for s in sessions],
            # The recurring weekly pattern, for days whose periods haven't
            # been generated yet.
            'weekly': [{
                'day': line.day,
                'period': line.timing_id.display_name,
                'subject': ref(line.subject_id),
                'class': ref(line.timetable_id.course_id),
                'section': ref(line.timetable_id.batch_id),
            } for line in weekly],
        })

    @http.route('/api/v1/teacher/classes', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def classes(self, **kwargs):
        faculty, error = _require_faculty(request.env)
        if error:
            return error
        context = school_context(request.env)
        lines = request.env['bxi.timetable.line'].sudo().search([('teacher_id', '=', faculty.id)])
        result = []
        for batch in context['teaching_batches'].sorted(lambda b: (b.course_id.name or '', b.name)):
            subjects = lines.filtered(lambda line: line.timetable_id.batch_id == batch).subject_id
            result.append({
                'section': ref(batch),
                'class': ref(batch.course_id),
                'is_class_teacher': batch.class_teacher_id == faculty,
                'subjects': [ref(s) for s in subjects],
                'student_count': len(_section_students(batch)),
            })
        return api_response({'classes': result})

    @http.route('/api/v1/teacher/classes/<int:batch_id>/students', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def class_students(self, batch_id, **kwargs):
        faculty, error = _require_faculty(request.env)
        if error:
            return error
        batch = request.env['op.batch'].sudo().browse(batch_id)
        if not batch.exists():
            return api_error('Section not found.', status=404, code='not_found')
        if batch not in school_context(request.env)['teaching_batches']:
            return api_error('You do not teach this section.', status=403, code='forbidden')
        return api_response({'section': ref(batch), 'class': ref(batch.course_id), 'students': [{
            'id': s.id,
            'name': s.name,
            'roll_number': running_enrollment(s).roll_number or None,
            'gr_no': s.gr_no or None,
            'gender': s.gender,
            'has_photo': bool(s.image_128),
        } for s in _section_students(batch)]})

    # -- activity log -------------------------------------------------------

    @http.route('/api/v1/students/<int:student_id>/activities', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def student_activities(self, student_id, **kwargs):
        student, error = get_viewable_student(request.env, student_id)
        if error:
            return error
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Activity = request.env['op.activity'].sudo()
        domain = [('student_id', '=', student.id)]
        total = Activity.search_count(domain)
        activities = Activity.search(domain, limit=limit, offset=offset, order='date desc, id desc')
        return api_response({'activities': [{
            'id': a.id,
            'date': date_str(a.date),
            'type': ref(a.type_id),
            'description': a.description or None,
            'teacher': ref(a.faculty_id),
        } for a in activities]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/activities', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def log_activity(self, **kwargs):
        """A teacher logs an activity/behaviour note for one of their
        students: {student_id, type_id, description, date?}."""
        context = school_context(request.env)
        is_manager = any(request.env.user.has_group(g) for g in ACTIVITY_MANAGER_GROUPS)
        if not context['faculty'] and not is_manager:
            return api_error('Only teachers can log activities.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        student, error = get_viewable_student(request.env, payload.get('student_id'))
        if error:
            return error
        if not is_manager and running_enrollment(student).batch_id not in context['teaching_batches']:
            return api_error('You do not teach this student.', status=403, code='forbidden')
        vals = {
            'student_id': student.id,
            'faculty_id': context['faculty'].id or False,
            'description': payload.get('description') or False,
            'date': payload.get('date') or fields.Date.context_today(student),
        }
        if payload.get('type_id'):
            vals['type_id'], error = parse_int(payload['type_id'], 'type_id')
            if error:
                return error
        activity, error = safe_create(request.env['op.activity'].sudo(), vals)
        if error:
            return error
        return api_response({'id': activity.id, 'date': date_str(activity.date), 'type': ref(activity.type_id),
                             'description': activity.description or None}, status=201)
