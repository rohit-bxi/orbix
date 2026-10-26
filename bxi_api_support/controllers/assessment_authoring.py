# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Question authoring for digital assessments (bxi_assessment_hub): the
teacher-side counterpart of assessment.py - questions with answer options,
file import, AI generation and re-evaluation of a graded submission."""
import base64

from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import (
    api_error, api_response, call_action, parse_int, parse_request, require_auth,
)

from .assessment import _exam_dict, _is_coordinator_or_manager, _submission_dict
from .common import get_own_faculty, safe_create

QUESTION_FIELDS = ('question_type', 'question_text', 'marks', 'sample_answer_keywords', 'sequence')
QUESTION_TYPES = ('mcq', 'short_answer', 'long_answer')


def _can_author(env, exam):
    return _is_coordinator_or_manager(env.user) or exam.teacher_id.user_id == env.user


def _question_dict(question):
    return {
        'id': question.id,
        'sequence': question.sequence,
        'question_type': question.question_type,
        'question_text': question.question_text,
        'marks': question.marks,
        'sample_answer_keywords': question.sample_answer_keywords or None,
        'options': [{
            'id': o.id, 'label': o.label, 'option_text': o.option_text, 'is_correct': o.is_correct,
        } for o in question.option_ids],
    }


def _question_vals(payload):
    """(vals, error) from a question payload; options replace the existing
    ones when given."""
    vals = {k: payload[k] for k in QUESTION_FIELDS if k in payload}
    if 'question_type' in vals and vals['question_type'] not in QUESTION_TYPES:
        return None, api_error('question_type must be one of %s.' % ', '.join(QUESTION_TYPES),
                               status=400, code='invalid_question_type')
    if 'options' in payload:
        options = payload['options'] or []
        if any(not (o or {}).get('option_text') for o in options):
            return None, api_error('Every option needs option_text.', status=400, code='invalid_option')
        vals['option_ids'] = [(5, 0, 0)] + [(0, 0, {
            'option_text': o['option_text'], 'is_correct': bool(o.get('is_correct')), 'sequence': i * 10,
        }) for i, o in enumerate(options, start=1)]
    return vals, None


class BxiApiSupportAssessmentAuthoringController(http.Controller):

    def _editable_exam(self, exam_id):
        exam = request.env['bxi.exam'].sudo().browse(exam_id)
        if not exam.exists():
            return None, api_error('Exam not found.', status=404, code='not_found')
        if not _can_author(request.env, exam):
            return None, api_error('Not authorized for this exam.', status=403, code='forbidden')
        return exam, None

    @http.route('/api/v1/assessments/exams/<int:exam_id>/questions', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_questions(self, exam_id, **kwargs):
        """The full paper with correct answers - teachers/coordinators only;
        students see questions through their submission instead."""
        exam, error = self._editable_exam(exam_id)
        if error:
            return error
        return api_response({'exam': _exam_dict(exam), 'questions': [_question_dict(q) for q in exam.question_ids]})

    @http.route('/api/v1/assessments/exams/<int:exam_id>/questions', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def add_question(self, exam_id, **kwargs):
        exam, error = self._editable_exam(exam_id)
        if error:
            return error
        if exam.state != 'draft':
            return api_error('Questions can only be changed while the exam is a draft.', status=400, code='exam_published')
        payload = request.get_json_data() or {}
        if not payload.get('question_text'):
            return api_error('question_text is required.', status=400, code='missing_question_text')
        vals, error = _question_vals(payload)
        if error:
            return error
        question, error = safe_create(request.env['bxi.exam.question'].sudo(), dict(vals, exam_id=exam.id))
        if error:
            return error
        return api_response(_question_dict(question), status=201)

    @http.route('/api/v1/assessments/questions/<int:question_id>/<any("update", "delete"):action>',
                type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def change_question(self, question_id, action, **kwargs):
        question = request.env['bxi.exam.question'].sudo().browse(question_id)
        if not question.exists():
            return api_error('Question not found.', status=404, code='not_found')
        exam, error = self._editable_exam(question.exam_id.id)
        if error:
            return error
        if exam.state != 'draft':
            return api_error('Questions can only be changed while the exam is a draft.', status=400, code='exam_published')
        if action == 'delete':
            question.unlink()
            return api_response({'deleted': True, 'id': question_id})
        vals, error = _question_vals(request.get_json_data() or {})
        if error:
            return error
        _, error = call_action(question, 'write', vals=vals)
        if error:
            return error
        return api_response(_question_dict(question))

    @http.route('/api/v1/assessments/exams/<int:exam_id>/import-questions', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def import_questions(self, exam_id, **kwargs):
        """Upload an .xlsx/.docx/.pdf question file (multipart `file`, or
        JSON base64 `attachments`), parsed by the module's import wizard."""
        exam, error = self._editable_exam(exam_id)
        if error:
            return error
        if exam.state != 'draft':
            return api_error('Questions can only be changed while the exam is a draft.', status=400, code='exam_published')
        _payload, files, error = parse_request()
        if error:
            return error
        if not files:
            return api_error('A question file is required.', status=400, code='missing_file')
        before = len(exam.question_ids)
        wizard, error = safe_create(request.env['bxi.exam.question.import.wizard'].sudo(), {
            'exam_id': exam.id, 'upload_file': base64.b64encode(files[0]['content']), 'file_name': files[0]['name'],
        })
        if error:
            return error
        _, error = call_action(wizard, 'action_import')
        if error:
            return error
        return api_response({'imported': len(exam.question_ids) - before,
                             'questions': [_question_dict(q) for q in exam.question_ids]}, status=201)

    @http.route('/api/v1/assessments/exams/ai-generate', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def ai_generate(self, **kwargs):
        """{class_id, subject_id, topic, difficulty?, question_count?,
        exam_id?}: generate questions with the configured AI provider into a
        new draft exam, or replace the questions of `exam_id`."""
        payload = request.get_json_data() or {}
        faculty = get_own_faculty(request.env)
        if not faculty and not _is_coordinator_or_manager(request.env.user):
            return api_error('Only teachers can generate assessments.', status=403, code='forbidden')
        for required in ('class_id', 'subject_id', 'topic'):
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        vals = {k: payload[k] for k in ('topic', 'difficulty', 'question_count') if payload.get(k)}
        for key in ('class_id', 'subject_id', 'exam_id'):
            if payload.get(key):
                vals[key], error = parse_int(payload[key], key)
                if error:
                    return error
        if vals.get('exam_id'):
            exam, error = self._editable_exam(vals['exam_id'])
            if error:
                return error
            if exam.state != 'draft':
                return api_error('Questions can only be changed while the exam is a draft.', status=400,
                                 code='exam_published')
        wizard, error = safe_create(request.env['bxi.ai.assignment.generate.wizard'].sudo(), vals)
        if error:
            return error
        result, error = call_action(wizard, 'action_generate')
        if error:
            return error
        exam = wizard.exam_id or request.env['bxi.exam'].sudo().browse((result or {}).get('res_id'))
        if faculty and not exam.teacher_id:
            exam.teacher_id = faculty
        return api_response(dict(_exam_dict(exam), questions=[_question_dict(q) for q in exam.question_ids]), status=201)

    @http.route('/api/v1/assessments/submissions/<int:submission_id>/re-evaluate', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def re_evaluate(self, submission_id, **kwargs):
        """{marks_adjustment, reason}: adjust a graded submission's score
        with an audit note, via the module's re-evaluation wizard."""
        submission = request.env['bxi.assessment.submission'].sudo().browse(submission_id)
        if not submission.exists():
            return api_error('Submission not found.', status=404, code='not_found')
        if not _can_author(request.env, submission.exam_id):
            return api_error('Not authorized for this submission.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        if not payload.get('reason'):
            return api_error('reason is required.', status=400, code='missing_reason')
        wizard, error = safe_create(request.env['bxi.assessment.reevaluation.wizard'].sudo(), {
            'submission_id': submission.id,
            'marks_adjustment': payload.get('marks_adjustment') or 0.0,
            'reason': payload['reason'],
        })
        if error:
            return error
        _, error = call_action(wizard, 'action_confirm')
        if error:
            return error
        return api_response(_submission_dict(submission))
