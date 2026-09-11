# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, parse_int, require_auth

from .common import get_own_faculty, get_own_student_ids, parse_pagination, safe_create

COORDINATOR_GROUP = 'bxi_academic_management.group_academic_coordinator'
MANAGER_GROUP = 'bxi_academic_management.group_academic_manager'


def _is_coordinator_or_manager(user):
    return user.has_group(COORDINATOR_GROUP) or user.has_group(MANAGER_GROUP)


def _exam_dict(exam):
    return {
        'id': exam.id,
        'name': exam.name,
        'class': exam.class_id.display_name,
        'subject': exam.subject_id.display_name,
        'teacher': exam.teacher_id.display_name,
        'duration': exam.duration,
        'source': exam.source,
        'state': exam.state,
        'question_count': exam.question_count,
        'total_marks': exam.total_marks,
    }


def _session_dict(session):
    return {
        'id': session.id,
        'name': session.name,
        'exam_id': session.exam_id.id,
        'class': session.class_id.display_name,
        'teacher': session.teacher_id.display_name,
        'exam_date': session.exam_date and session.exam_date.isoformat(),
        'exam_time': session.exam_time,
        'total_marks': session.total_marks,
        'state': session.state,
        'submission_count': session.submission_count,
        'student_ids': session.student_ids.ids,
    }


def _submission_dict(submission):
    return {
        'id': submission.id,
        'name': submission.name,
        'session_id': submission.session_id.id,
        'exam_id': submission.exam_id.id,
        'student_id': submission.student_id.id,
        'status': submission.status,
        'submitted_at': submission.submitted_at and submission.submitted_at.isoformat(),
        'max_score': submission.max_score,
        'computed_score': submission.computed_score,
        'manual_adjustment': submission.manual_adjustment,
        'total_score': submission.total_score,
        'answers': [{
            'id': a.id, 'question_id': a.question_id.id, 'question_text': a.question_id.question_text,
            'question_type': a.question_type, 'marks': a.marks,
            'student_answer_text': a.student_answer_text,
            'selected_option_id': a.selected_option_id.id or None,
            'awarded_marks': a.awarded_marks,
        } for a in submission.answer_ids],
    }


class BxiApiSupportAssessmentController(http.Controller):

    # -- Exams ---------------------------------------------------------------

    @http.route('/api/v1/assessments/exams', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_exams(self, **kwargs):
        user = request.env.user
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        if _is_coordinator_or_manager(user):
            domain = []
        else:
            faculty = get_own_faculty(request.env)
            domain = [('teacher_id', '=', faculty.id)] if faculty else [('id', '=', 0)]
        Exam = request.env['bxi.exam'].sudo()
        total = Exam.search_count(domain)
        exams = Exam.search(domain, limit=limit, offset=offset, order='id desc')
        return api_response(
            {'exams': [_exam_dict(e) for e in exams]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/assessments/exams/<int:exam_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_exam(self, exam_id, **kwargs):
        exam = request.env['bxi.exam'].sudo().browse(exam_id)
        if not exam.exists():
            return api_error('Exam not found.', status=404, code='not_found')
        return api_response(_exam_dict(exam))

    @http.route('/api/v1/assessments/exams', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_exam(self, **kwargs):
        payload = request.get_json_data() or {}
        if not payload.get('name'):
            return api_error('name is required.', status=400, code='missing_name')
        if not payload.get('class_id'):
            return api_error('class_id is required.', status=400, code='missing_class_id')
        if not payload.get('subject_id'):
            return api_error('subject_id is required.', status=400, code='missing_subject_id')

        faculty = get_own_faculty(request.env)
        teacher_id = faculty.id if faculty else None
        vals = {
            'name': payload['name'], 'class_id': payload['class_id'], 'subject_id': payload['subject_id'],
            'duration': payload.get('duration', 60),
        }
        if teacher_id:
            vals['teacher_id'] = teacher_id
        exam = request.env['bxi.exam'].sudo().create(vals)
        return api_response(_exam_dict(exam), status=201)

    @http.route('/api/v1/assessments/exams/<int:exam_id>/publish', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def publish_exam(self, exam_id, **kwargs):
        return self._transition_exam(exam_id, 'action_publish')

    @http.route('/api/v1/assessments/exams/<int:exam_id>/reset-to-draft', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reset_exam(self, exam_id, **kwargs):
        return self._transition_exam(exam_id, 'action_reset_to_draft')

    def _transition_exam(self, exam_id, method_name):
        exam = request.env['bxi.exam'].sudo().browse(exam_id)
        if not exam.exists():
            return api_error('Exam not found.', status=404, code='not_found')
        if not _is_coordinator_or_manager(request.env.user) and exam.teacher_id.user_id.id != request.env.user.id:
            return api_error('Not authorized for this exam.', status=403, code='forbidden')
        _, error = call_action(exam, method_name)
        if error:
            return error
        return api_response(_exam_dict(exam))

    # -- Sessions --------------------------------------------------------------

    @http.route('/api/v1/assessments/sessions', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_sessions(self, **kwargs):
        user = request.env.user
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        if _is_coordinator_or_manager(user):
            domain = []
        else:
            faculty = get_own_faculty(request.env)
            domain = [('teacher_id', '=', faculty.id)] if faculty else [('id', '=', 0)]
        Session = request.env['bxi.assessment.session'].sudo()
        total = Session.search_count(domain)
        sessions = Session.search(domain, limit=limit, offset=offset, order='id desc')
        return api_response(
            {'sessions': [_session_dict(s) for s in sessions]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/assessments/sessions/<int:session_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_session(self, session_id, **kwargs):
        session = request.env['bxi.assessment.session'].sudo().browse(session_id)
        if not session.exists():
            return api_error('Session not found.', status=404, code='not_found')
        return api_response(_session_dict(session))

    @http.route('/api/v1/assessments/sessions', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_session(self, **kwargs):
        payload = request.get_json_data() or {}
        if not payload.get('exam_id'):
            return api_error('exam_id is required.', status=400, code='missing_exam_id')
        if not payload.get('class_id'):
            return api_error('class_id is required.', status=400, code='missing_class_id')
        if not payload.get('student_ids'):
            return api_error('student_ids is required.', status=400, code='missing_student_ids')

        faculty = get_own_faculty(request.env)
        vals = {
            'exam_id': payload['exam_id'], 'class_id': payload['class_id'],
            'student_ids': [(6, 0, payload['student_ids'])],
        }
        if payload.get('exam_date'):
            vals['exam_date'] = payload['exam_date']
        if payload.get('exam_time') is not None:
            vals['exam_time'] = payload['exam_time']
        if faculty:
            vals['teacher_id'] = faculty.id
        session, error = safe_create(request.env['bxi.assessment.session'].sudo(), vals)
        if error:
            return error
        return api_response(_session_dict(session), status=201)

    @http.route('/api/v1/assessments/sessions/<int:session_id>/cancel', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def cancel_session(self, session_id, **kwargs):
        session = request.env['bxi.assessment.session'].sudo().browse(session_id)
        if not session.exists():
            return api_error('Session not found.', status=404, code='not_found')
        if not _is_coordinator_or_manager(request.env.user) and session.teacher_id.user_id.id != request.env.user.id:
            return api_error('Not authorized for this session.', status=403, code='forbidden')
        _, error = call_action(session, 'action_cancel')
        if error:
            return error
        return api_response(_session_dict(session))

    @http.route('/api/v1/assessments/sessions/<int:session_id>/autograde-all', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def autograde_session(self, session_id, **kwargs):
        session = request.env['bxi.assessment.session'].sudo().browse(session_id)
        if not session.exists():
            return api_error('Session not found.', status=404, code='not_found')
        if not _is_coordinator_or_manager(request.env.user) and session.teacher_id.user_id.id != request.env.user.id:
            return api_error('Not authorized for this session.', status=403, code='forbidden')

        submissions = session.submission_ids.filtered(lambda s: s.status == 'submitted')
        if not submissions:
            return api_error('No submitted submissions to grade for this session.', status=400, code='nothing_to_grade')
        wizard = request.env['bxi.assessment.autograde.wizard'].sudo().create({
            'submission_ids': [(6, 0, submissions.ids)],
        })
        _, error = call_action(wizard, 'action_start_grading')
        if error:
            return error
        return api_response({
            'graded_count': wizard.graded_count, 'failed_count': wizard.failed_count,
            'submissions': [_submission_dict(s) for s in submissions],
        })

    # -- Submissions -------------------------------------------------------------

    @http.route('/api/v1/assessments/submissions', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_submissions(self, session_id=None, **kwargs):
        user = request.env.user
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        if _is_coordinator_or_manager(user):
            domain = []
        else:
            faculty = get_own_faculty(request.env)
            own_student_ids = get_own_student_ids(request.env)
            if faculty:
                domain = [('session_id.teacher_id', '=', faculty.id)]
            elif own_student_ids:
                domain = [('student_id', 'in', own_student_ids)]
            else:
                domain = [('id', '=', 0)]
        if session_id:
            session_id, error = parse_int(session_id, 'session_id')
            if error:
                return error
            domain = domain + [('session_id', '=', session_id)]
        Submission = request.env['bxi.assessment.submission'].sudo()
        total = Submission.search_count(domain)
        submissions = Submission.search(domain, limit=limit, offset=offset, order='id desc')
        return api_response(
            {'submissions': [_submission_dict(s) for s in submissions]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/assessments/submissions/<int:submission_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_submission(self, submission_id, **kwargs):
        submission, error = self._authorized_submission(submission_id)
        if error:
            return error
        return api_response(_submission_dict(submission))

    @http.route('/api/v1/assessments/submissions/<int:submission_id>/answers', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def submit_answers(self, submission_id, **kwargs):
        submission, error = self._authorized_submission(submission_id)
        if error:
            return error
        payload = request.get_json_data() or {}
        answers = payload.get('answers') or []
        by_question = {a.question_id.id: a for a in submission.answer_ids}
        for entry in answers:
            question_id = entry.get('question_id')
            answer = by_question.get(question_id)
            if not answer:
                continue
            vals = {}
            if 'student_answer_text' in entry:
                vals['student_answer_text'] = entry['student_answer_text']
            if 'selected_option_id' in entry:
                vals['selected_option_id'] = entry['selected_option_id']
            if vals:
                answer.write(vals)
        return api_response(_submission_dict(submission))

    @http.route('/api/v1/assessments/submissions/<int:submission_id>/mark-submitted', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def mark_submitted(self, submission_id, **kwargs):
        submission, error = self._authorized_submission(submission_id)
        if error:
            return error
        _, error = call_action(submission, 'action_mark_submitted')
        if error:
            return error
        return api_response(_submission_dict(submission))

    @http.route('/api/v1/assessments/submissions/<int:submission_id>/auto-grade', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def auto_grade(self, submission_id, **kwargs):
        submission = request.env['bxi.assessment.submission'].sudo().browse(submission_id)
        if not submission.exists():
            return api_error('Submission not found.', status=404, code='not_found')
        if not _is_coordinator_or_manager(request.env.user) \
                and submission.session_id.teacher_id.user_id.id != request.env.user.id:
            return api_error('Not authorized for this submission.', status=403, code='forbidden')
        _, error = call_action(submission, 'action_auto_grade')
        if error:
            return error
        return api_response(_submission_dict(submission))

    def _authorized_submission(self, submission_id):
        submission = request.env['bxi.assessment.submission'].sudo().browse(submission_id)
        if not submission.exists():
            return None, api_error('Submission not found.', status=404, code='not_found')
        user = request.env.user
        if _is_coordinator_or_manager(user):
            return submission, None
        if submission.session_id.teacher_id.user_id.id == user.id:
            return submission, None
        if submission.student_id.id in get_own_student_ids(request.env):
            return submission, None
        return None, api_error('Not authorized for this submission.', status=403, code='forbidden')
