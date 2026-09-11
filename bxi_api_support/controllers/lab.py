# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import get_own_faculty, parse_pagination, safe_create

INSTRUCTOR_GROUP = 'op_student_lab_management.group_lab_instructor'
ADMIN_GROUP = 'op_student_lab_management.group_lab_admin'


def _is_lab_admin(user):
    return user.has_group(ADMIN_GROUP)


def _is_lab_staff(user):
    return user.has_group(INSTRUCTOR_GROUP) or user.has_group(ADMIN_GROUP)


def _session_dict(session):
    return {
        'id': session.id,
        'room': session.room_id.display_name,
        'course': session.course_id.display_name,
        'batch': session.batch_id.display_name,
        'faculty': session.faculty_id.display_name,
        'experiment': session.experiment_id.display_name,
        'date': session.date and session.date.isoformat(),
        'start_time': session.start_time,
        'end_time': session.end_time,
        'state': session.state,
        'student_ids': session.student_ids.ids,
    }


def _issue_dict(issue):
    return {
        'id': issue.id,
        'session_id': issue.session_id.id,
        'equipment': issue.equipment_id.display_name,
        'student_id': issue.student_id.id or None,
        'issued_qty': issue.issued_qty,
        'returned_qty': issue.returned_qty,
        'issue_date': issue.issue_date and issue.issue_date.isoformat(),
        'return_date': issue.return_date and issue.return_date.isoformat(),
        'state': issue.state,
    }


class BxiApiSupportLabController(http.Controller):

    @http.route('/api/v1/lab/sessions', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_sessions(self, **kwargs):
        user = request.env.user
        if not _is_lab_staff(user):
            return api_error('Not authorized to view lab sessions.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        if _is_lab_admin(user):
            domain = []
        else:
            faculty = get_own_faculty(request.env)
            domain = [('faculty_id', '=', faculty.id)] if faculty else [('id', '=', 0)]
        Session = request.env['lab.session'].sudo()
        total = Session.search_count(domain)
        sessions = Session.search(domain, limit=limit, offset=offset, order='date desc, start_time desc')
        return api_response(
            {'sessions': [_session_dict(s) for s in sessions]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/lab/sessions/<int:session_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_session(self, session_id, **kwargs):
        session, error = self._authorized_session(session_id)
        if error:
            return error
        return api_response(_session_dict(session))

    @http.route('/api/v1/lab/sessions', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_session(self, **kwargs):
        if not _is_lab_staff(request.env.user):
            return api_error('Not authorized to schedule lab sessions.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        for field in ('room_id', 'course_id', 'batch_id', 'start_time', 'end_time'):
            if payload.get(field) is None:
                return api_error('%s is required.' % field, status=400, code='missing_%s' % field)

        vals = {key: payload[key] for key in (
            'room_id', 'course_id', 'batch_id', 'subject_id', 'experiment_id', 'date', 'start_time', 'end_time',
        ) if key in payload}
        if payload.get('student_ids'):
            vals['student_ids'] = [(6, 0, payload['student_ids'])]
        faculty = get_own_faculty(request.env)
        if payload.get('faculty_id'):
            vals['faculty_id'] = payload['faculty_id']
        elif faculty:
            vals['faculty_id'] = faculty.id
        else:
            return api_error('faculty_id is required.', status=400, code='missing_faculty_id')

        session, error = safe_create(request.env['lab.session'].sudo(), vals)
        if error:
            return error
        return api_response(_session_dict(session), status=201)

    @http.route('/api/v1/lab/sessions/<int:session_id>/confirm', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def confirm_session(self, session_id, **kwargs):
        return self._transition(session_id, 'action_confirm')

    @http.route('/api/v1/lab/sessions/<int:session_id>/start', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def start_session(self, session_id, **kwargs):
        return self._transition(session_id, 'action_start')

    @http.route('/api/v1/lab/sessions/<int:session_id>/done', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def done_session(self, session_id, **kwargs):
        return self._transition(session_id, 'action_done')

    @http.route('/api/v1/lab/sessions/<int:session_id>/cancel', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def cancel_session(self, session_id, **kwargs):
        return self._transition(session_id, 'action_cancel')

    @http.route('/api/v1/lab/sessions/<int:session_id>/reset', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reset_session(self, session_id, **kwargs):
        return self._transition(session_id, 'action_reset_draft')

    def _transition(self, session_id, method_name):
        session, error = self._authorized_session(session_id)
        if error:
            return error
        _, error = call_action(session, method_name)
        if error:
            return error
        return api_response(_session_dict(session))

    def _authorized_session(self, session_id):
        session = request.env['lab.session'].sudo().browse(session_id)
        if not session.exists():
            return None, api_error('Lab session not found.', status=404, code='not_found')
        user = request.env.user
        if _is_lab_admin(user) or session.faculty_id.user_id.id == user.id:
            return session, None
        return None, api_error('Not authorized for this session.', status=403, code='forbidden')

    @http.route('/api/v1/lab/equipment-issues', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_issues(self, session_id=None, **kwargs):
        user = request.env.user
        if not _is_lab_staff(user):
            return api_error('Not authorized to view equipment issues.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        if _is_lab_admin(user):
            domain = []
        else:
            faculty = get_own_faculty(request.env)
            domain = [('session_id.faculty_id', '=', faculty.id)] if faculty else [('id', '=', 0)]
        if session_id:
            domain = domain + [('session_id', '=', int(session_id))]
        Issue = request.env['lab.equipment.issue'].sudo()
        total = Issue.search_count(domain)
        issues = Issue.search(domain, limit=limit, offset=offset)
        return api_response(
            {'issues': [_issue_dict(i) for i in issues]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/lab/equipment-issues/<int:issue_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_issue(self, issue_id, **kwargs):
        issue, error = self._authorized_issue(issue_id)
        if error:
            return error
        return api_response(_issue_dict(issue))

    @http.route('/api/v1/lab/equipment-issues', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_issue(self, **kwargs):
        payload = request.get_json_data() or {}
        if not payload.get('session_id'):
            return api_error('session_id is required.', status=400, code='missing_session_id')
        if not payload.get('equipment_id'):
            return api_error('equipment_id is required.', status=400, code='missing_equipment_id')
        session, error = self._authorized_session(payload['session_id'])
        if error:
            return error
        vals = {key: payload[key] for key in ('equipment_id', 'student_id', 'issued_qty', 'issue_date') if key in payload}
        vals['session_id'] = session.id
        issue, error = safe_create(request.env['lab.equipment.issue'].sudo(), vals)
        if error:
            return error
        return api_response(_issue_dict(issue), status=201)

    @http.route('/api/v1/lab/equipment-issues/<int:issue_id>/return', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def return_issue(self, issue_id, **kwargs):
        issue, error = self._authorized_issue(issue_id)
        if error:
            return error
        payload = request.get_json_data() or {}
        if payload.get('returned_qty') is not None:
            issue.returned_qty = payload['returned_qty']
        _, error = call_action(issue, 'action_return')
        if error:
            return error
        return api_response(_issue_dict(issue))

    @http.route('/api/v1/lab/equipment-issues/<int:issue_id>/mark-damaged', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def mark_damaged_issue(self, issue_id, **kwargs):
        issue, error = self._authorized_issue(issue_id)
        if error:
            return error
        _, error = call_action(issue, 'action_mark_damaged')
        if error:
            return error
        return api_response(_issue_dict(issue))

    def _authorized_issue(self, issue_id):
        issue = request.env['lab.equipment.issue'].sudo().browse(issue_id)
        if not issue.exists():
            return None, api_error('Equipment issue not found.', status=404, code='not_found')
        user = request.env.user
        if _is_lab_admin(user) or issue.session_id.faculty_id.user_id.id == user.id:
            return issue, None
        return None, api_error('Not authorized for this equipment issue.', status=403, code='forbidden')
