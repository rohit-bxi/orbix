# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The student app's home: the dashboard in one call, career guidance,
the calendar's "Work Areas" study tips and the school's Info page. All of
it is worked out from the school's own data - nothing is sent to an
outside AI service."""
import base64
from datetime import timedelta

import pytz

from odoo import fields, http
from odoo.http import request
from odoo.tools.mimetypes import guess_mimetype

from odoo.addons.bxi_api.controllers.auth import api_error, api_file_response, api_response, require_auth

from .academic_admin import _school_tz
from .assignment import _student_tasks, _task_counts
from .common import date_str, get_app_student, ref, running_enrollment

WEAK_SUBJECT_BELOW = 75.0
RECENT_TESTS = 3


def _attendance_label(percentage, total):
    if not total:
        return None
    return 'excellent' if percentage >= 90 else 'good' if percentage >= 75 else 'needs_attention'


def _student_sessions(student, start, end):
    enrollment = running_enrollment(student)
    if not enrollment:
        return request.env['op.session']
    return request.env['op.session'].sudo().search([
        '|', ('student_ids', 'in', student.id), '&', ('student_ids', '=', False), ('batch_id', '=', enrollment.batch_id.id),
        ('start_datetime', '>=', start), ('start_datetime', '<', end), ('state', '!=', 'cancel'),
    ], order='start_datetime')


def _today_bounds():
    """(today, start, end): today in the school's time zone, with its bounds
    as naive UTC datetimes."""
    zone = _school_tz(request.env(su=True))  # the school's calendar is staff-only
    today = fields.Datetime.now().replace(tzinfo=pytz.utc).astimezone(zone).date()
    start = zone.localize(fields.Datetime.to_datetime(today)).astimezone(pytz.utc).replace(tzinfo=None)
    return today, start, start + timedelta(days=1)


def _recent_tests(student, limit=RECENT_TESTS):
    """Latest exam marks and graded online tests, newest first."""
    env = request.env
    tests = []
    for line in env['op.result.line'].sudo().search([('student_id', '=', student.id)], order='id desc', limit=limit):
        exam = line.exam_id
        tests.append({
            'type': 'exam', 'id': line.id, 'name': exam.name, 'subject': ref(exam.subject_id),
            'date': date_str(exam.start_time), 'grade': line.grade or None,
            'percentage': round(100.0 * line.marks / exam.total_marks, 1) if exam.total_marks else None,
            'sort': exam.start_time or fields.Datetime.now(),
        })
    if 'bxi.assessment.submission' in env:
        for submission in env['bxi.assessment.submission'].sudo().search(
                [('student_id', '=', student.id), ('status', 'in', ('auto_graded', 'reviewed'))],
                order='submitted_at desc, id desc', limit=limit):
            tests.append({
                'type': 'assessment', 'id': submission.id, 'name': submission.exam_id.name,
                'subject': ref(submission.exam_id.subject_id), 'date': date_str(submission.submitted_at),
                'grade': None,
                'percentage': round(100.0 * submission.total_score / submission.max_score, 1)
                if submission.max_score else None,
                'sort': submission.submitted_at or fields.Datetime.now(),
            })
    tests.sort(key=lambda t: t['sort'], reverse=True)
    for test in tests:
        test.pop('sort')
    return tests[:limit]


def _careers(student):
    return [{
        'id': row['career'].id, 'name': row['career'].name, 'description': row['career'].description or None,
        'icon': row['career'].icon or None, 'demand': row['career'].demand, 'match': row['match'],
        'matched_subjects': row['matched_subjects'],
    } for row in request.env['bxi.career'].sudo()._bxi_recommend(student)]


class BxiApiSupportStudentAppController(http.Controller):

    @http.route('/api/v1/student/dashboard', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def dashboard(self, student_id=None, **kwargs):
        """The student home screen in one call: attendance this month,
        homework counts, today's timetable, books, career recommendations,
        recent test papers, doubts and the latest community posts. A
        student's own login (or a one-child parent) may leave student_id out."""
        env = request.env
        student, error = get_app_student(env, student_id)
        if error:
            return error
        enrollment = running_enrollment(student)
        today, day_start, day_end = _today_bounds()
        month_rows = student._get_attendance_rows(today.replace(day=1), today)
        month = student._summarize_attendance_rows(month_rows)
        sessions = _student_sessions(student, day_start, day_end)
        now = fields.Datetime.now()
        upcoming = sessions.filtered(lambda s: s.end_datetime and s.end_datetime > now)[:1]

        tasks = _student_tasks(student)
        reading = env['bxi.reading.progress'].sudo().search([('student_id', '=', student.id)])
        doubts = env['bxi.student.doubt'].sudo().search([('student_id', '=', student.id)])
        posts = env['bxi.community.post'].sudo().search([
            ('batch_id', '=', enrollment.batch_id.id), ('state', '=', 'visible')], limit=3) if enrollment else []
        digital = env['op.media'].sudo().search_count([('attachment_ids', '!=', False)])
        smart_books = 0
        if 'slide.channel' in env:
            smart_books = env['slide.channel'].search_count([('website_published', '=', True), ('is_member', '=', True)])
        today_answered = doubts.filtered(
            lambda d: d.answered_at and fields.Datetime.context_timestamp(d, d.answered_at).date() == today)
        return api_response({
            'student': {
                'id': student.id, 'name': student.name, 'gr_no': student.gr_no or None,
                'class': ref(enrollment.course_id) if enrollment else None,
                'section': ref(enrollment.batch_id) if enrollment else None,
                'roll_number': enrollment.roll_number or None if enrollment else None,
                'academic_year': ref(enrollment.academic_years_id) if enrollment else None,
            },
            'attendance': {
                'month': date_str(today.replace(day=1))[:7],
                'percentage': month['percentage'], 'present': month['present'], 'total': month['total'],
                'label': _attendance_label(month['percentage'], month['total']),
            },
            'homework': _task_counts(tasks),
            'timetable': {
                'classes_today': len(sessions),
                'next_class': {
                    'id': upcoming.id, 'subject': upcoming.subject_id.name or None,
                    'teacher': upcoming.faculty_id.name or None,
                    'start_datetime': date_str(upcoming.start_datetime),
                    'is_live': bool(upcoming.start_datetime <= now),
                } if upcoming else None,
            },
            'books': {
                'smart_books': smart_books, 'digital_library': digital,
                'reading_now': len(reading.filtered(lambda r: not r.completed)),
                'completed': len(reading.filtered('completed')),
            },
            'careers': _careers(student),
            'recent_tests': _recent_tests(student),
            'doubts': {
                'open': len(doubts.filtered(lambda d: d.state == 'open')),
                'solved_today': len(today_answered),
                'latest_question': doubts[:1].question if doubts else None,
            },
            'community': [{
                'id': p.id, 'kind': p.kind, 'title': p.title, 'author': p.author_id.name,
                'created_at': date_str(p.create_date), 'reply_count': len(p.reply_ids.filtered(
                    lambda r: r.state == 'visible')), 'likes': len(p.like_user_ids),
            } for p in posts],
        })

    @http.route('/api/v1/student/careers', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def careers(self, student_id=None, **kwargs):
        """Career recommendations ("View Report"): each match % comes from
        the student's results in the subjects that career leans on, and
        `scores` shows those subject averages."""
        student, error = get_app_student(request.env, student_id)
        if error:
            return error
        scores = student._bxi_subject_scores()
        return api_response({
            'careers': _careers(student),
            'scores': [{'subject': name, 'percentage': pct} for name, pct in sorted(scores.items())],
            'method': 'rules',
        })

    @http.route('/api/v1/student/study-tips', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def study_tips(self, student_id=None, **kwargs):
        """The Smart Calendar's "Work Areas": revision before exams in the
        next 7 days, the weakest subject, homework due within 2 days and a
        study slot after today's last class."""
        env = request.env
        student, error = get_app_student(env, student_id)
        if error:
            return error
        enrollment = running_enrollment(student)
        tips = []
        now = fields.Datetime.now()
        if enrollment:
            exams = env['op.exam'].sudo().search([
                ('session_id.course_id', '=', enrollment.course_id.id),
                '|', ('session_id.batch_id', '=', False), ('session_id.batch_id', '=', enrollment.batch_id.id),
                ('session_id.state', 'in', ('schedule', 'held')), ('state', '!=', 'cancel'),
                ('start_time', '>=', now), ('start_time', '<=', now + timedelta(days=7))], order='start_time', limit=3)
            for exam in exams:
                subject = exam.subject_id.name or exam.name
                tips.append({'type': 'exam_revision', 'subject': subject, 'date': date_str(exam.start_time),
                             'text': 'Schedule 2 hours of %s revision before your exam' % subject})
        scores = student._bxi_subject_scores()
        if scores:
            subject, pct = min(scores.items(), key=lambda kv: kv[1])
            if pct < WEAK_SUBJECT_BELOW:
                tips.append({'type': 'weak_area', 'subject': subject, 'percentage': pct,
                             'text': 'Focus on %s - your weak area' % subject})
        soon = now + timedelta(days=2)
        for assignment, _sub, status in _student_tasks(student):
            if status in ('due_today', 'upcoming') and assignment.submission_date and assignment.submission_date <= soon:
                tips.append({'type': 'homework_due', 'assignment_id': assignment.id,
                             'date': date_str(assignment.submission_date),
                             'text': 'Finish "%s" before it is due' % assignment.name})
        today, day_start, day_end = _today_bounds()
        sessions = _student_sessions(student, day_start, day_end)
        if sessions:
            last_end = max(sessions.mapped('end_datetime'))
            local = fields.Datetime.context_timestamp(sessions[0], last_end + timedelta(hours=1))
            tips.append({'type': 'study_time', 'from': local.strftime('%H:%M'),
                         'to': (local + timedelta(hours=2)).strftime('%H:%M'),
                         'text': 'Best study time for you: %s - %s' % (
                             local.strftime('%I:%M %p'), (local + timedelta(hours=2)).strftime('%I:%M %p'))})
        return api_response({'tips': tips, 'method': 'rules'})

    @http.route('/api/v1/school/info', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def school_info(self, **kwargs):
        """The app's Info page: the school's tagline, mission, picture, core
        values and team (company settings) with live student / teacher /
        parent counts."""
        env = request.env
        company = env.company.sudo()
        return api_response({
            'title': company.bxi_about_title or 'About %s' % company.name,
            'tagline': company.bxi_about_tagline or None,
            'mission': company.bxi_about_mission or None,
            # Bearer-token downloads (the app has no web session for /web/image).
            'image_url': '/api/v1/school/info/image' if company.bxi_about_image else None,
            'stats': {
                'students': env['op.student'].sudo().search_count([]),
                'teachers': env['op.faculty'].sudo().search_count([]),
                'parents': env['op.parent'].sudo().search_count([]),
                'success_rate': company.bxi_about_success_rate or None,
            },
            'values': [{'name': v.name, 'description': v.description or None, 'icon': v.icon or None}
                       for v in company.bxi_value_ids],
            'team': [{
                'id': m.id, 'name': m.name, 'role': m.role or None, 'bio': m.bio or None,
                'image_url': '/api/v1/school/team/%s/image' % m.id if m.image else None,
            } for m in company.bxi_team_member_ids],
        })

    @http.route(['/api/v1/school/info/image', '/api/v1/school/team/<int:member_id>/image'], type='http',
                auth='public', methods=['GET'], csrf=False)
    @require_auth
    def school_image(self, member_id=None, **kwargs):
        company = request.env.company.sudo()
        if member_id:
            member = company.bxi_team_member_ids.filtered(lambda m: m.id == member_id)
            raw, name = member.image, 'team-%s' % member_id
        else:
            raw, name = company.bxi_about_image, 'about'
        if not raw:
            return api_error('No picture.', status=404, code='not_found')
        content = base64.b64decode(raw)
        mimetype = guess_mimetype(content, default='image/png')
        return api_file_response(content, '%s.%s' % (name, mimetype.split('/')[-1]), mimetype=mimetype)
