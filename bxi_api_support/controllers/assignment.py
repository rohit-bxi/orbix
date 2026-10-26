# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Homework (openeducat_assignment): families read and students submit;
teachers create, publish, close and review."""
import base64

from odoo import fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import (
    api_error, api_file_response, api_response, call_action, parse_int, parse_request, require_auth,
)

from .common import (
    date_str, get_viewable_student, parse_ids, parse_pagination, ref, running_enrollment, safe_create,
    school_context,
)

MANAGER_GROUPS = (
    'openeducat_assignment.group_op_assignment_manager',
    'bxi_academic_management.group_academic_coordinator',
    'bxi_academic_management.group_academic_manager',
)
FAMILY_VISIBLE_STATES = ('publish', 'finish')
SUBMITTABLE_STATES = (False, 'draft', 'change')
CREATE_FIELDS = ('name', 'description', 'marks')


def _is_manager(user):
    return any(user.has_group(group) for group in MANAGER_GROUPS)


def _can_manage(env, assignment):
    """The assignment's own teacher or an assignment/academic manager."""
    return _is_manager(env.user) or assignment.faculty_id.user_id == env.user


def _attachments(record):
    return request.env['ir.attachment'].sudo().search([
        ('res_model', '=', record._name), ('res_id', '=', record.id),
    ])


def _attachment_list(record):
    return [{'id': a.id, 'name': a.name, 'mimetype': a.mimetype, 'size': a.file_size} for a in _attachments(record)]


def _store_files(record, files):
    request.env['ir.attachment'].sudo().create([{
        'name': f['name'], 'datas': base64.b64encode(f['content']), 'mimetype': f['mimetype'],
        'res_model': record._name, 'res_id': record.id,
    } for f in files])


def _submission_dict(sub):
    if not sub:
        return None
    return {
        'id': sub.id,
        'student': ref(sub.student_id),
        'state': sub.state,
        'description': sub.description or None,
        'submission_date': date_str(sub.submission_date),
        'is_late': bool(sub.submission_date and sub.assignment_id.submission_date
                        and sub.submission_date > sub.assignment_id.submission_date),
        'marks': sub.marks if sub.state == 'accept' else None,
        'note': sub.note or None,
        'attachments': _attachment_list(sub),
    }


def _assignment_dict(assignment, submission=None, detail=False):
    data = {
        'id': assignment.id,
        'name': assignment.name,
        'subject': ref(assignment.subject_id),
        'class': ref(assignment.course_id),
        'section': ref(assignment.batch_id),
        'teacher': ref(assignment.faculty_id),
        'type': ref(assignment.assignment_type),
        'issued_date': date_str(assignment.issued_date),
        'submission_date': date_str(assignment.submission_date),
        'marks': assignment.marks,
        'state': assignment.state,
        'is_overdue': bool(assignment.submission_date and assignment.submission_date < fields.Datetime.now()),
    }
    if submission is not None:
        data['my_submission'] = _submission_dict(submission)
    if detail:
        data['description'] = assignment.description
        data['attachments'] = _attachment_list(assignment)
    return data


def _own_submission(assignment, student):
    return request.env['op.assignment.sub.line'].sudo().search([
        ('assignment_id', '=', assignment.id), ('student_id', '=', student.id),
    ], limit=1)


class BxiApiSupportAssignmentController(http.Controller):

    # -- family / student ---------------------------------------------------

    @http.route('/api/v1/assignments', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_assignments(self, student_id=None, state=None, **kwargs):
        """With student_id: that student's published homework (family view,
        each with `my_submission`). Without: the teacher's own assignments
        (managers: all), optionally ?state=draft|publish|finish|cancel."""
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Assignment = request.env['op.assignment'].sudo()
        if student_id:
            student, error = get_viewable_student(request.env, student_id)
            if error:
                return error
            domain = [('allocation_ids', 'in', student.id), ('state', 'in', FAMILY_VISIBLE_STATES)]
            if state == 'pending':
                submitted = request.env['op.assignment.sub.line'].sudo().search([
                    ('student_id', '=', student.id), ('state', 'in', ('submit', 'accept')),
                ]).assignment_id
                domain += [('state', '=', 'publish'), ('id', 'not in', submitted.ids)]
            total = Assignment.search_count(domain)
            assignments = Assignment.search(domain, limit=limit, offset=offset)
            return api_response({'assignments': [
                _assignment_dict(a, submission=_own_submission(a, student)) for a in assignments
            ]}, meta={'total': total, 'limit': limit, 'offset': offset})

        context = school_context(request.env)
        if _is_manager(request.env.user):
            domain = []
        elif context['faculty']:
            domain = [('faculty_id', '=', context['faculty'].id)]
        else:
            return api_error('student_id is required.', status=400, code='missing_student_id')
        if state:
            domain.append(('state', '=', state))
        total = Assignment.search_count(domain)
        assignments = Assignment.search(domain, limit=limit, offset=offset)
        return api_response(
            {'assignments': [dict(_assignment_dict(a), submission_count=a.assignment_sub_line_count) for a in assignments]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/assignments/<int:assignment_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_assignment(self, assignment_id, student_id=None, **kwargs):
        assignment, student, error = self._resolve(assignment_id, student_id)
        if error:
            return error
        return api_response(_assignment_dict(
            assignment, submission=_own_submission(assignment, student) if student else None, detail=True))

    @http.route('/api/v1/assignments/<int:assignment_id>/my-submission', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def my_submission(self, assignment_id, student_id=None, **kwargs):
        if not student_id:
            return api_error('student_id is required.', status=400, code='missing_student_id')
        assignment, student, error = self._resolve(assignment_id, student_id)
        if error:
            return error
        return api_response({'submission': _submission_dict(_own_submission(assignment, student))})

    @http.route('/api/v1/assignments/<int:assignment_id>/submit', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def submit(self, assignment_id, **kwargs):
        """The student's own submission (multipart files, or JSON with
        base64 `attachments`) plus an optional `description`. Only the
        student login itself may submit - openeducat blocks parents from
        creating submissions. Resubmitting is allowed while the submission
        is a draft or the teacher asked for changes."""
        payload, files, error = parse_request()
        if error:
            return error
        student = school_context(request.env)['student']
        if not student:
            return api_error('Only the student can submit homework.', status=403, code='forbidden')
        assignment = request.env['op.assignment'].sudo().browse(assignment_id)
        if not assignment.exists() or student not in assignment.allocation_ids:
            return api_error('Assignment not found.', status=404, code='not_found')
        if assignment.state != 'publish':
            return api_error('This assignment is not open for submissions.', status=400, code='invalid_transition')
        if not files and not payload.get('description'):
            return api_error('Add a description or at least one file.', status=400, code='missing_content')

        submission = _own_submission(assignment, student)
        if submission.state not in SUBMITTABLE_STATES:
            return api_error('This homework has already been submitted.', status=400, code='already_submitted')
        vals = {'description': payload.get('description') or submission.description or False,
                'submission_date': fields.Datetime.now()}
        if submission:
            submission.write(vals)
        else:
            submission, error = safe_create(request.env['op.assignment.sub.line'].sudo(), dict(
                vals, assignment_id=assignment.id, student_id=student.id))
            if error:
                return error
        _store_files(submission, files)
        _, error = call_action(submission, 'act_submit')
        if error:
            return error
        return api_response(_submission_dict(submission), status=201)

    @http.route('/api/v1/assignments/attachments/<int:attachment_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def download_attachment(self, attachment_id, student_id=None, **kwargs):
        attachment = request.env['ir.attachment'].sudo().browse(attachment_id)
        if not attachment.exists() or attachment.res_model not in ('op.assignment', 'op.assignment.sub.line'):
            return api_error('File not found.', status=404, code='not_found')
        record = request.env[attachment.res_model].sudo().browse(attachment.res_id)
        assignment = record if attachment.res_model == 'op.assignment' else record.assignment_id
        if not _can_manage(request.env, assignment):
            context = school_context(request.env)
            allowed = assignment.allocation_ids & context['students'] if assignment.state in FAMILY_VISIBLE_STATES else False
            if attachment.res_model == 'op.assignment.sub.line':
                allowed = allowed and record.student_id in allowed
            if not allowed:
                return api_error('Not authorized for this file.', status=403, code='forbidden')
        return api_file_response(attachment.raw or b'', attachment.name, attachment.mimetype or 'application/octet-stream')

    # -- teacher ------------------------------------------------------------

    @http.route('/api/v1/assignments', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_assignment(self, **kwargs):
        """Teacher creates homework for one of their sections. It's allocated
        to every student currently in that section unless `student_ids`
        narrows it. Created as a draft - publish it to notify families."""
        payload, files, error = parse_request()
        if error:
            return error
        context = school_context(request.env)
        faculty = context['faculty']
        if not faculty and not _is_manager(request.env.user):
            return api_error('Only teachers can create homework.', status=403, code='forbidden')
        for required in ('name', 'description', 'batch_id', 'subject_id', 'submission_date', 'assignment_type_id'):
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        ids = {}
        for key in ('batch_id', 'subject_id', 'assignment_type_id', 'faculty_id'):
            if payload.get(key):
                ids[key], error = parse_int(payload[key], key)
                if error:
                    return error
        batch = request.env['op.batch'].sudo().browse(ids['batch_id'])
        if not batch.exists():
            return api_error('Section not found.', status=404, code='not_found')
        if not _is_manager(request.env.user) and batch not in context['teaching_batches']:
            return api_error('You do not teach this section.', status=403, code='forbidden')
        if _is_manager(request.env.user) and ids.get('faculty_id'):
            faculty = request.env['op.faculty'].sudo().browse(ids['faculty_id'])
        if not faculty:
            return api_error('faculty_id is required.', status=400, code='missing_faculty_id')

        students = request.env['op.student.course'].sudo().search([
            ('batch_id', '=', batch.id), ('state', '=', 'running'),
        ]).student_id
        if payload.get('student_ids'):
            wanted, error = parse_ids(payload['student_ids'], 'student_ids')
            if error:
                return error
            students = students.filtered(lambda s: s.id in wanted)
        vals = {k: payload[k] for k in CREATE_FIELDS if k in payload}
        vals.update({
            'course_id': batch.course_id.id,
            'batch_id': batch.id,
            'subject_id': ids['subject_id'],
            'assignment_type': ids['assignment_type_id'],
            'faculty_id': faculty.id,
            'issued_date': payload.get('issued_date') or fields.Datetime.now(),
            'submission_date': payload['submission_date'],
            'allocation_ids': [(6, 0, students.ids)],
        })
        assignment, error = safe_create(request.env['op.assignment'].sudo(), vals)
        if error:
            return error
        _store_files(assignment, files)
        return api_response(_assignment_dict(assignment, detail=True), status=201)

    @http.route('/api/v1/assignments/<int:assignment_id>/<any("publish", "finish", "cancel", "reset-to-draft"):action>',
                type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def transition(self, assignment_id, action, **kwargs):
        assignment = request.env['op.assignment'].sudo().browse(assignment_id)
        if not assignment.exists():
            return api_error('Assignment not found.', status=404, code='not_found')
        if not _can_manage(request.env, assignment):
            return api_error('Not authorized for this assignment.', status=403, code='forbidden')
        allowed_from = {'publish': ('draft',), 'finish': ('publish',), 'cancel': ('draft', 'publish'),
                        'reset-to-draft': ('cancel',)}
        if assignment.state not in allowed_from[action]:
            return api_error(f"Can't {action} an assignment that is {assignment.state}.",
                             status=400, code='invalid_transition')
        method = {'publish': 'act_publish', 'finish': 'act_finish', 'cancel': 'act_cancel',
                  'reset-to-draft': 'act_set_to_draft'}[action]
        _, error = call_action(assignment, method)
        if error:
            return error
        return api_response(_assignment_dict(assignment, detail=True))

    @http.route('/api/v1/assignments/<int:assignment_id>/submissions', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_submissions(self, assignment_id, **kwargs):
        assignment = request.env['op.assignment'].sudo().browse(assignment_id)
        if not assignment.exists():
            return api_error('Assignment not found.', status=404, code='not_found')
        if not _can_manage(request.env, assignment):
            return api_error('Not authorized for this assignment.', status=403, code='forbidden')
        by_student = {s.student_id.id: s for s in assignment.assignment_sub_line}
        return api_response({
            'assignment': _assignment_dict(assignment),
            'submissions': [dict(
                _submission_dict(by_student[s.id]) if s.id in by_student else {'id': None, 'state': 'not_submitted'},
                student=ref(s), roll_number=running_enrollment(s).roll_number or None,
            ) for s in assignment.allocation_ids],
        })

    @http.route('/api/v1/assignments/submissions/<int:submission_id>/<any("accept", "reject", "request-changes"):action>',
                type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def review_submission(self, submission_id, action, **kwargs):
        submission = request.env['op.assignment.sub.line'].sudo().browse(submission_id)
        if not submission.exists():
            return api_error('Submission not found.', status=404, code='not_found')
        if not _can_manage(request.env, submission.assignment_id):
            return api_error('Not authorized for this submission.', status=403, code='forbidden')
        if submission.state != 'submit':
            return api_error('Only a submitted homework can be reviewed.', status=400, code='invalid_transition')
        payload = request.get_json_data() or {}
        vals = {}
        if payload.get('note') is not None:
            vals['note'] = payload['note']
        if action == 'accept' and payload.get('marks') is not None:
            vals['marks'] = payload['marks']
        if vals:
            _, error = call_action(submission, 'write', vals=vals)
            if error:
                return error
        method = {'accept': 'act_accept', 'reject': 'act_reject', 'request-changes': 'act_change_req'}[action]
        _, error = call_action(submission, method)
        if error:
            return error
        return api_response(_submission_dict(submission))

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _resolve(assignment_id, student_id):
        """(assignment, student_or_None, error): a teacher/manager of the
        assignment sees it as-is; family sees it only once published and
        allocated to the given (or their only) student."""
        assignment = request.env['op.assignment'].sudo().browse(assignment_id)
        if not assignment.exists():
            return None, None, api_error('Assignment not found.', status=404, code='not_found')
        if _can_manage(request.env, assignment) and not student_id:
            return assignment, None, None
        if not student_id:
            students = school_context(request.env)['students'] & assignment.allocation_ids
            if len(students) != 1:
                return None, None, api_error('student_id is required.', status=400, code='missing_student_id')
            student_id = students.id
        student, error = get_viewable_student(request.env, student_id)
        if error:
            return None, None, error
        if student not in assignment.allocation_ids or assignment.state not in FAMILY_VISIBLE_STATES:
            return None, None, api_error('Assignment not found.', status=404, code='not_found')
        return assignment, student, None
