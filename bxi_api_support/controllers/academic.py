# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import atomic, is_staff, json_body, parse_pagination, resolve_record, resolve_records, school_context

COORDINATOR_GROUP = 'bxi_academic_management.group_academic_coordinator'
MANAGER_GROUP = 'bxi_academic_management.group_academic_manager'


def _is_coordinator_or_manager(user):
    return user.has_group(COORDINATOR_GROUP) or user.has_group(MANAGER_GROUP)


def _curriculum_dict(curriculum):
    return {
        'id': curriculum.id,
        'name': curriculum.name,
        'board': curriculum.board_id.display_name,
        'board_id': curriculum.board_id.id or None,
        'description': curriculum.description,
        'classes': curriculum.class_ids.mapped('display_name'),
        'class_ids': curriculum.class_ids.ids,
        'classes_detail': [{'id': c.id, 'name': c.display_name} for c in curriculum.class_ids],
        'approval_status': curriculum.approval_status,
        'locked': curriculum.locked,
    }


class _Refused(Exception):
    """Raised inside atomic() to roll back with an error response (e.g. a
    board created for a curriculum that turns out to be a duplicate)."""

    def __init__(self, response):
        super().__init__()
        self.response = response


def _atomic(func):
    try:
        return atomic(func)
    except _Refused as exc:
        return None, exc.response


def _blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _board(payload):
    """(bxi.board or None when not sent, error): "board_id", or "board" as
    typed on the screen (CBSE, ICSE, State Board) - matched by name
    ignoring case, created when new."""
    if payload.get('board_id') not in (None, ''):
        board, error = resolve_record(request.env, 'bxi.board', payload['board_id'], 'board_id')
        return (None, error) if error else (board, None)
    if 'board' not in payload and 'board_id' not in payload:
        return None, None
    name = payload.get('board')
    if _blank(name) or not isinstance(name, str):
        return None, api_error('board is required.', status=400, code='missing_board')
    Board = request.env['bxi.board'].sudo().with_context(active_test=False)
    board = Board.search([('name', '=ilike', name.strip())], limit=1)
    if board and not board.active:
        board.active = True
    return board or Board.create({'name': name.strip()}), None


def _classes(payload, curriculum=None):
    """(op.course records or None when not sent, error): "class_ids" (the
    whole list), "class_id" (the Add screen's single class), or
    "add_class_ids" / "remove_class_ids" on update."""
    Course = request.env['op.course'].sudo()
    if 'class_ids' in payload or 'class_id' in payload:
        raw = payload['class_ids'] if 'class_ids' in payload else (
            [payload['class_id']] if payload['class_id'] not in (None, '') else [])
        classes, error = resolve_records(request.env, 'op.course', raw, 'class_ids')
        return (None, error) if error else (classes, None)
    if curriculum is not None and ('add_class_ids' in payload or 'remove_class_ids' in payload):
        added, error = resolve_records(request.env, 'op.course', payload.get('add_class_ids') or [], 'add_class_ids')
        if error:
            return None, error
        removed, error = resolve_records(request.env, 'op.course', payload.get('remove_class_ids') or [],
                                         'remove_class_ids')
        if error:
            return None, error
        return (curriculum.class_ids | added) - removed, None
    return (None, None) if curriculum is not None else (Course, None)


def _text(payload, key):
    """(value or None when not sent, error) for a required text field."""
    if key not in payload:
        return None, None
    if _blank(payload[key]) or not isinstance(payload[key], str):
        return None, api_error('%s is required.' % key, status=400, code='missing_%s' % key)
    return payload[key].strip(), None


def _duplicate_error(name, board, curriculum=None):
    domain = [('name', '=ilike', name), ('board_id', '=', board.id)]
    if curriculum:
        domain.append(('id', '!=', curriculum.id))
    if request.env['bxi.curriculum'].sudo().with_context(active_test=False).search_count(domain, limit=1):
        return api_error('A curriculum with this name already exists for %s.' % board.name, status=409,
                         code='curriculum_exists')
    return None


def _mapping_dict(mapping):
    return {
        'id': mapping.id,
        'subject': mapping.subject_id.display_name,
        'class': mapping.class_id.display_name,
        'teacher': mapping.teacher_id.display_name,
        'curriculum': mapping.curriculum_id.display_name,
    }


def _ptm_dict(meeting):
    return {
        'id': meeting.id,
        'name': meeting.name,
        'start_datetime': meeting.start_datetime and meeting.start_datetime.isoformat(),
        'end_datetime': meeting.end_datetime and meeting.end_datetime.isoformat(),
        'venue': meeting.venue,
        'classes': meeting.class_ids.mapped('display_name'),
    }


class BxiApiSupportAcademicController(http.Controller):

    @http.route('/api/v1/academic/curricula', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_curricula(self, **kwargs):
        # School setup data: staff only, not families.
        if not is_staff(request.env):
            return api_error('Not authorized to view curricula.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Curriculum = request.env['bxi.curriculum'].sudo()
        total = Curriculum.search_count([])
        curricula = Curriculum.search([], limit=limit, offset=offset, order='id desc')
        return api_response(
            {'curricula': [_curriculum_dict(c) for c in curricula]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/academic/curricula/<int:curriculum_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_curriculum(self, curriculum_id, **kwargs):
        if not is_staff(request.env):
            return api_error('Not authorized to view curricula.', status=403, code='forbidden')
        curriculum = request.env['bxi.curriculum'].sudo().browse(curriculum_id)
        if not curriculum.exists():
            return api_error('Curriculum not found.', status=404, code='not_found')
        return api_response(_curriculum_dict(curriculum))

    @http.route('/api/v1/academic/curricula', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_curriculum(self, **kwargs):
        """The Add Curriculum screen: {"name", "description", "board" (as
        typed - matched or created) or "board_id", "class_id" or
        "class_ids"} - all required. Academic coordinators and managers.
        A new curriculum is a draft; 409 curriculum_exists for the same name
        on the same board."""
        if not _is_coordinator_or_manager(request.env.user):
            return api_error('Not authorized to manage curricula.', status=403, code='forbidden')
        payload = json_body() or {}
        for key in ('name', 'description'):
            if key not in payload:
                return api_error('%s is required.' % key, status=400, code='missing_%s' % key)
        if 'board' not in payload and 'board_id' not in payload:
            return api_error('board is required.', status=400, code='missing_board')
        values = {}
        for key in ('name', 'description'):
            values[key], error = _text(payload, key)
            if error:
                return error
        classes, error = _classes(payload)
        if error:
            return error
        if not classes:
            return api_error('class_ids is required.', status=400, code='missing_class_ids')

        def create():
            board, error = _board(payload)
            if error:
                raise _Refused(error)
            error = _duplicate_error(values['name'], board)
            if error:
                # Also forgets a board created just for this request.
                raise _Refused(error)
            return request.env['bxi.curriculum'].sudo().create(dict(
                values, board_id=board.id, class_ids=[(6, 0, classes.ids)]))

        curriculum, error = _atomic(create)
        if error:
            return error
        return api_response(_curriculum_dict(curriculum), status=201)

    @http.route('/api/v1/academic/curricula/<int:curriculum_id>/update', type='http', auth='public',
                methods=['POST'], csrf=False)
    @require_auth
    def update_curriculum(self, curriculum_id, **kwargs):
        """The Edit Curriculum and Assign Classes screens: any of "name",
        "description", "board" / "board_id", "class_ids" (the whole list),
        "class_id", or "add_class_ids" / "remove_class_ids". Only the keys
        sent change. A locked curriculum keeps its board and classes (409
        curriculum_locked); an approved one whose board or classes change
        goes back to draft for approval again."""
        if not _is_coordinator_or_manager(request.env.user):
            return api_error('Not authorized to manage curricula.', status=403, code='forbidden')
        curriculum = request.env['bxi.curriculum'].sudo().browse(curriculum_id)
        if not curriculum.exists():
            return api_error('Curriculum not found.', status=404, code='not_found')
        payload = json_body() or {}
        values = {}
        for key in ('name', 'description'):
            value, error = _text(payload, key)
            if error:
                return error
            if value is not None:
                values[key] = value
        classes, error = _classes(payload, curriculum)
        if error:
            return error
        if classes is not None and not classes:
            return api_error('A curriculum needs at least one class.', status=400, code='missing_class_ids')

        def write():
            board, error = _board(payload)
            if error:
                raise _Refused(error)
            changed_scope = (board and board != curriculum.board_id) or \
                (classes is not None and classes != curriculum.class_ids)
            if changed_scope and curriculum.locked:
                raise _Refused(api_error('This curriculum is locked: unlock it to change its board or classes.',
                                         status=409, code='curriculum_locked'))
            error = _duplicate_error(values.get('name', curriculum.name), board or curriculum.board_id, curriculum)
            if error:
                raise _Refused(error)
            vals = dict(values)
            if board:
                vals['board_id'] = board.id
            if classes is not None:
                vals['class_ids'] = [(6, 0, classes.ids)]
            if changed_scope and curriculum.approval_status == 'approved':
                vals['approval_status'] = 'draft'
            if vals:
                curriculum.write(vals)
            return True

        _result, error = _atomic(write)
        if error:
            return error
        return api_response(_curriculum_dict(curriculum))

    @http.route('/api/v1/academic/curricula/<int:curriculum_id>/approve', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def approve_curriculum(self, curriculum_id, **kwargs):
        return self._transition(curriculum_id, 'action_approve')

    @http.route('/api/v1/academic/curricula/<int:curriculum_id>/reject', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reject_curriculum(self, curriculum_id, **kwargs):
        return self._transition(curriculum_id, 'action_reject')

    @http.route('/api/v1/academic/curricula/<int:curriculum_id>/reset', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reset_curriculum(self, curriculum_id, **kwargs):
        return self._transition(curriculum_id, 'action_reset_to_draft')

    @http.route('/api/v1/academic/curricula/<int:curriculum_id>/toggle-lock', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def toggle_lock_curriculum(self, curriculum_id, **kwargs):
        return self._transition(curriculum_id, 'action_toggle_lock')

    def _transition(self, curriculum_id, method_name):
        if not _is_coordinator_or_manager(request.env.user):
            return api_error('Not authorized to manage curricula.', status=403, code='forbidden')
        curriculum = request.env['bxi.curriculum'].sudo().browse(curriculum_id)
        if not curriculum.exists():
            return api_error('Curriculum not found.', status=404, code='not_found')
        _, error = call_action(curriculum, method_name)
        if error:
            return error
        return api_response(_curriculum_dict(curriculum))

    @http.route('/api/v1/academic/subject-mappings', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_subject_mappings(self, class_id=None, teacher_id=None, **kwargs):
        # Staff directory data; families aren't shown it, as with other staff lists.
        if not request.env.user.has_group('base.group_user'):
            return api_error('Not authorized to view subject mappings.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = []
        if class_id:
            domain.append(('class_id', '=', int(class_id)))
        if teacher_id:
            domain.append(('teacher_id', '=', int(teacher_id)))
        Mapping = request.env['bxi.subject.mapping'].sudo()
        total = Mapping.search_count(domain)
        mappings = Mapping.search(domain, limit=limit, offset=offset, order='id desc')
        return api_response(
            {'mappings': [_mapping_dict(m) for m in mappings]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/academic/ptm-meetings', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_ptm_meetings(self, **kwargs):
        user = request.env.user
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        if user.has_group('base.group_user'):
            domain = []
        else:
            domain = ['|', ('parent_ids.user_id', '=', user.id), ('teacher_ids.user_id', '=', user.id)]
        Meeting = request.env['bxi.ptm.meeting'].sudo()
        total = Meeting.search_count(domain)
        meetings = Meeting.search(domain, limit=limit, offset=offset, order='start_datetime desc')
        return api_response(
            {'meetings': [_ptm_dict(m) for m in meetings]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/academic/ptm-meetings/my', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def my_ptm_meetings(self, include_past=None, **kwargs):
        """PTMs the caller is expected at: invited by name, or - for a
        family - held for a child's class, and - for a teacher - for a class
        they teach. Upcoming only unless ?include_past=1."""
        context = school_context(request.env)
        parent, faculty = context['parent'], context['faculty']
        domain = Domain.FALSE
        if parent or context['students']:
            domain |= Domain('class_ids', 'in', context['family_courses'].ids)
        if parent:
            domain |= Domain('parent_ids', 'in', parent.id)
        if faculty:
            domain |= Domain('teacher_ids', 'in', faculty.id) | Domain('class_ids', 'in', context['teaching_courses'].ids)
        if include_past not in ('1', 'true', 'True'):
            domain &= Domain('end_datetime', '>=', fields.Datetime.now())
        meetings = request.env['bxi.ptm.meeting'].sudo().search(domain, order='start_datetime')
        return api_response({'meetings': [_ptm_dict(m) for m in meetings]})

    @http.route('/api/v1/academic/ptm-meetings/<int:meeting_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_ptm_meeting(self, meeting_id, **kwargs):
        meeting = request.env['bxi.ptm.meeting'].sudo().browse(meeting_id)
        if not meeting.exists():
            return api_error('PTM meeting not found.', status=404, code='not_found')
        user = request.env.user
        if not user.has_group('base.group_user') \
                and user.id not in meeting.parent_ids.mapped('user_id').ids \
                and user.id not in meeting.teacher_ids.mapped('user_id').ids:
            return api_error('Not authorized for this meeting.', status=403, code='forbidden')
        return api_response(_ptm_dict(meeting))
