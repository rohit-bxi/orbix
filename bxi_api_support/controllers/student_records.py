# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Student-wise screens: one student's weekly timetable, their books
(class Smart Books plus library loans) and their exams and online tests.

The student is `student_id` when sent - the family, the teachers of the
student's section and the office staff may ask for it - or, left out, the
caller's own student (the student login, or a parent's only child)."""
from odoo import fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth

from .common import date_str, get_app_student, ref, running_enrollment
from .exam import _student_sessions_domain
from .library import ACTIVE_LOAN_STATES, _loan_dict

DAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday')
# Offline exam papers whose marks are final and may be shown to the family.
RESULT_STATES = ('done',)
GRADED_SUBMISSION_STATES = ('auto_graded', 'reviewed')
EXAM_STATUSES = ('upcoming', 'completed', 'all')


def _hm(value):
    """Float hours (9.5) -> "09:30", or None."""
    if value is None or value is False:
        return None
    minutes = int(round(value * 60))
    return '%02d:%02d' % divmod(minutes, 60)


def _student_header(student):
    enrollment = running_enrollment(student)
    return {
        'id': student.id,
        'name': student.name,
        'class': ref(enrollment.course_id),
        'section': ref(enrollment.batch_id),
        'roll_number': enrollment.roll_number or None if enrollment else None,
    }


def _elearning_books(env, student):
    """The Smart Book screen's cards: the eLearning courses the student has
    joined, with "Chapter 5 of 12", completion and hours left. Empty when
    eLearning is not installed or the student has no login partner."""
    if 'slide.channel.partner' not in env or not student.partner_id:
        return []
    members = env['slide.channel.partner'].sudo().search([
        ('partner_id', '=', student.partner_id.id), ('member_status', '!=', 'invited'),
        ('channel_id.is_published', '=', True)])
    Slide = env['slide.slide'].sudo()
    done = set(env['slide.slide.partner'].sudo().search([
        ('partner_id', '=', student.partner_id.id), ('completed', '=', True)]).slide_id.ids)
    result = []
    for member in members.sorted(lambda m: (m.channel_id.name or '', m.id)):
        channel = member.channel_id
        lessons = Slide.search([('channel_id', '=', channel.id), ('website_published', '=', True),
                                ('is_category', '=', False)], order='sequence, id')
        pending = lessons.filtered(lambda s: s.id not in done)
        current = pending[:1] or lessons[-1:]
        result.append({
            'id': channel.id,
            'name': channel.name,
            'tags': [tag.name for tag in channel.tag_ids],
            'completion': member.completion,
            'completed': not pending and bool(lessons),
            'chapter_index': list(lessons).index(current) + 1 if current else 0,
            'chapter_count': len(lessons),
            'current_lesson': ref(current),
            'hours_left': round(sum(pending.mapped('completion_time')), 2),
        })
    return result


def _percent(score, total):
    return round(100.0 * score / total, 1) if total else None


class BxiApiSupportStudentRecordsController(http.Controller):

    # -- Timetable --------------------------------------------------------------

    @http.route('/api/v1/student/timetable', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def timetable(self, student_id=None, day=None, **kwargs):
        """The student's weekly timetable: their section's periods, Monday
        to Saturday, each with its time slot, subject and teacher. `day`
        (monday..saturday) narrows it to one day. For dated periods with
        holidays use /parent/timetable."""
        env = request.env
        student, error = get_app_student(env, student_id)
        if error:
            return error
        if day and day not in DAYS:
            return api_error('day must be one of: %s.' % ', '.join(DAYS), status=400, code='invalid_day')
        enrollment = running_enrollment(student)
        timetable = env['bxi.timetable'].sudo().search([
            ('course_id', '=', enrollment.course_id.id), ('batch_id', '=', enrollment.batch_id.id),
        ], limit=1) if enrollment else env['bxi.timetable']
        today = fields.Date.context_today(env['bxi.timetable']).strftime('%A').lower()
        lines = timetable.line_ids
        days = []
        for key in DAYS:
            if day and key != day:
                continue
            periods = lines.filtered(lambda line, key=key: line.day == key).sorted(
                lambda line: (line.timing_id.start_time, line.timing_id.id))
            days.append({
                'day': key,
                'label': key.capitalize(),
                'is_today': key == today,
                'periods': [{
                    'id': line.id,
                    'period': {'id': line.timing_id.id, 'name': line.timing_id.name},
                    'start_time': _hm(line.timing_id.start_time),
                    'end_time': _hm(line.timing_id.end_time),
                    'subject': ref(line.subject_id),
                    'teacher': ref(line.teacher_id),
                } for line in periods],
            })
        timings = lines.timing_id.sorted(lambda t: (t.start_time, t.id))
        return api_response({
            'student': _student_header(student),
            'timetable_id': timetable.id or None,
            'today': today if today in DAYS else None,
            'time_slots': [{'id': t.id, 'name': t.name, 'start_time': _hm(t.start_time),
                            'end_time': _hm(t.end_time)} for t in timings],
            'days': days,
            'total_periods': len(lines),
            'message': None if timetable else 'No timetable has been set up for this section yet.',
        })

    # -- Books ------------------------------------------------------------------

    @http.route('/api/v1/student/books', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def books(self, student_id=None, subject_id=None, **kwargs):
        """The student's books: `smart_books` - the Smart Books of their
        class from an approved curriculum, with their reading progress -
        and `library` - the library books they have out now, due dates and
        fines - plus `elearning_books`, the eLearning courses they joined
        ("Chapter 5 of 12", hours left). `subject_id` filters smart_books."""
        env = request.env
        student, error = get_app_student(env, student_id)
        if error:
            return error
        enrollment = running_enrollment(student)
        domain = [('curriculum_id', '!=', False), ('curriculum_id.approval_status', '=', 'approved'),
                  ('course_ids', 'in', enrollment.course_id.ids or [0])]
        if subject_id:
            subject_id, error = parse_int(subject_id, 'subject_id')
            if error:
                return error
            domain.append(('subject_ids', 'in', [subject_id]))
        books = env['op.media'].sudo().search(domain, order='name, id')
        progress = {p.media_id: p for p in env['bxi.reading.progress'].sudo().search([
            ('student_id', '=', student.id), ('media_id', 'in', books.ids)])}

        def book_dict(book):
            read = progress.get(book)
            return {
                'id': book.id,
                'title': book.name,
                'subjects': [ref(s) for s in book.subject_ids],
                'curriculum': ref(book.curriculum_id),
                'authors': [a.name for a in book.author_ids],
                'has_file': bool(book.attachment_ids),
                'progress': {
                    'percent': round(read.percent, 1), 'current_page': read.current_page or None,
                    'total_pages': read.total_pages or None, 'chapter': read.chapter or None,
                    'last_read': date_str(read.last_read), 'completed': read.completed,
                } if read else None,
            }

        loans = env['op.media.movement'].sudo().search([
            ('student_id', '=', student.id), ('state', 'in', ACTIVE_LOAN_STATES)],
            order='return_date, id')
        loan_rows = [_loan_dict(loan) for loan in loans]
        returned = env['op.media.movement'].sudo().search_count([
            ('student_id', '=', student.id), ('state', 'not in', ACTIVE_LOAN_STATES)])
        courses = _elearning_books(env, student)
        return api_response({
            'student': _student_header(student),
            'summary': {
                'smart_books': len(books),
                'completed': len([b for b in books if progress.get(b) and progress[b].completed]),
                'in_progress': len([b for b in books if progress.get(b) and not progress[b].completed]),
                'library_books_out': len(loan_rows),
                'overdue': len([row for row in loan_rows if row['is_overdue']]),
                'library_books_returned': returned,
                'elearning_books': len(courses),
            },
            'smart_books': [book_dict(book) for book in books],
            'elearning_books': courses,
            'library': loan_rows,
        })

    # -- Exams and tests --------------------------------------------------------

    @http.route('/api/v1/student/exams', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def exams(self, student_id=None, status='all', **kwargs):
        """The student's exams and tests: `exams` - offline exam papers of
        their class (time, room, marks once the paper is Done) - and
        `tests` - online tests assigned to them (date, duration, their
        submission and score once graded). `status`: upcoming, completed
        or all (default)."""
        env = request.env
        student, error = get_app_student(env, student_id)
        if error:
            return error
        status = status or 'all'
        if status not in EXAM_STATUSES:
            return api_error('status must be one of: %s.' % ', '.join(EXAM_STATUSES),
                             status=400, code='invalid_status')
        now = fields.Datetime.now()
        today = fields.Date.context_today(env['op.exam'])

        sessions = env['op.exam.session'].sudo().search(_student_sessions_domain(student))
        papers = sessions.exam_ids.filtered(lambda e: e.state != 'cancel').sorted(lambda e: (e.start_time, e.id))
        exams = []
        for paper in papers:
            attendee = paper.attendees_line.filtered(lambda a: a.student_id == student)[:1]
            paper_status = 'completed' if paper.state in ('held', 'result_updated', 'done') or (
                paper.end_time and paper.end_time < now) else 'upcoming'
            result = None
            if paper.state in RESULT_STATES and attendee:
                result = {
                    'attendance': attendee.status,
                    'marks': attendee.marks if attendee.status == 'present' else None,
                    'total_marks': paper.total_marks,
                    'percentage': _percent(attendee.marks, paper.total_marks) if attendee.status == 'present' else None,
                    'passed': attendee.status == 'present' and attendee.marks >= paper.min_marks,
                }
            exams.append({
                'id': paper.id,
                'type': 'exam',
                'name': paper.name,
                'exam_session': ref(paper.session_id),
                'exam_type': ref(paper.session_id.exam_type),
                'subject': ref(paper.subject_id),
                'start_time': date_str(paper.start_time),
                'end_time': date_str(paper.end_time),
                'room': ref(attendee.room_id),
                'total_marks': paper.total_marks,
                'passing_marks': paper.min_marks,
                'state': paper.state,
                'status': paper_status,
                'result': result,
            })

        submissions = env['bxi.assessment.submission'].sudo().search([
            ('student_id', '=', student.id), ('session_id.state', '!=', 'cancelled')])
        tests = []
        for submission in submissions.sorted(lambda s: (s.session_id.exam_date, s.session_id.exam_time, s.id)):
            session = submission.session_id
            graded = submission.status in GRADED_SUBMISSION_STATES
            test_status = 'completed' if (submission.status != 'not_submitted' or session.state == 'completed'
                                          or session.exam_date < today) else 'upcoming'
            tests.append({
                'id': submission.id,
                'type': 'test',
                'session_id': session.id,
                'name': submission.exam_id.name,
                'subject': ref(submission.exam_id.subject_id),
                'teacher': ref(session.teacher_id),
                'date': date_str(session.exam_date),
                'time': _hm(session.exam_time),
                'duration_minutes': submission.exam_id.duration,
                'questions': submission.exam_id.question_count,
                'total_marks': submission.max_score,
                'submission_status': submission.status,
                'submitted_at': date_str(submission.submitted_at),
                'status': test_status,
                'score': submission.total_score if graded else None,
                'percentage': _percent(submission.total_score, submission.max_score) if graded else None,
            })

        scored = [e['result']['percentage'] for e in exams if e['result'] and e['result']['percentage'] is not None]
        scored += [t['percentage'] for t in tests if t['percentage'] is not None]
        summary = {
            'upcoming_exams': len([e for e in exams if e['status'] == 'upcoming']),
            'completed_exams': len([e for e in exams if e['status'] == 'completed']),
            'upcoming_tests': len([t for t in tests if t['status'] == 'upcoming']),
            'completed_tests': len([t for t in tests if t['status'] == 'completed']),
            'average_percentage': round(sum(scored) / len(scored), 1) if scored else None,
        }
        if status != 'all':
            exams = [e for e in exams if e['status'] == status]
            tests = [t for t in tests if t['status'] == status]
        return api_response({
            'student': _student_header(student),
            'summary': summary,
            'exams': exams,
            'tests': tests,
        })
