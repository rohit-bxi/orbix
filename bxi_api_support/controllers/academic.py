# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import datetime
import re

from odoo import fields, http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, parse_int, require_auth

from odoo.addons.bxi_academic_management.models.exam_schedule import ExamScheduleError

from .common import (
    atomic, date_str, is_staff, json_body, parse_date, parse_pagination, ref, resolve_record, resolve_records,
    school_context,
)
from .exam import _is_exam_staff

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


# -- Smart Books (op.media mapped to a curriculum) -----------------------------

CURRICULUM_STATUSES = ('draft', 'approved', 'rejected')


def _smart_book_dict(book):
    curriculum = book.curriculum_id
    return {
        'id': book.id,
        'title': book.name,
        'subjects': [{'id': s.id, 'name': s.display_name} for s in book.subject_ids],
        'subject_ids': book.subject_ids.ids,
        'classes': [{'id': c.id, 'name': c.display_name} for c in book.course_ids],
        'class_ids': book.course_ids.ids,
        'curriculum': {'id': curriculum.id, 'name': curriculum.display_name,
                       'approval_status': curriculum.approval_status} if curriculum else None,
        'curriculum_id': curriculum.id or None,
        'locked': book.bxi_locked,
        'active': book.active,
    }


def _named_list(payload, model, key):
    """(records or None when not sent, error) for the Subject / Class
    inputs: "<key>_ids" (ids), "<key>_id" (one id) or "<key>s" as typed on
    the screen - a list of names or one comma-separated string ("Class 9,
    Class 10"), each matching one existing record by name or code,
    ignoring case. Nothing is created here."""
    ids_key, id_key, names_key = '%s_ids' % key, '%s_id' % key, '%ses' % key if key == 'class' else '%ss' % key
    env = request.env
    if ids_key in payload:
        return resolve_records(env, model, payload[ids_key] or [], ids_key)
    if id_key in payload:
        raw = payload[id_key]
        return resolve_records(env, model, [] if raw in (None, '') else [raw], ids_key)
    if names_key not in payload:
        return None, None
    names = payload[names_key]
    if isinstance(names, str):
        names = names.split(',')
    if names is None:
        names = []
    if not isinstance(names, list):
        return None, api_error('%s must be a list of names.' % names_key, status=400, code='invalid_%s' % names_key)
    records = env[model].sudo()
    for name in names:
        name = str(name or '').strip()
        if not name:
            continue
        found, error = _match_name(model, name, key, ids_key)
        if error:
            return None, error
        records |= found
    return records, None


# Titles the screens' examples carry ("Dr. Sarah Johnson") that the
# teacher's name does not.
TEACHER_TITLES = re.compile(r'^(dr|mr|mrs|ms|miss|prof)\.?\s+', re.IGNORECASE)


def _match_name(model, name, key, id_key):
    """(the one record named `name`, error): by name, else by code,
    ignoring case; a teacher also without a title. Nothing is created."""
    Model = request.env[model].sudo()
    candidates = [name]
    if model == 'op.faculty':
        bare = TEACHER_TITLES.sub('', name).strip()
        if bare and bare != name:
            candidates.append(bare)
    found = Model.browse()
    for candidate in candidates:
        found = Model.search([('name', '=ilike', candidate)])
        if not found and 'code' in Model._fields:
            found = Model.search([('code', '=ilike', candidate)])
        if found:
            break
    if not found:
        return None, api_error('No %s named "%s".' % (key, name), status=400, code='unknown_%s' % key)
    if len(found) > 1:
        return None, api_error('More than one %s is named "%s": send %s instead.' % (key, name, id_key),
                               status=400, code='ambiguous_%s' % key)
    return found, None


def _smart_book_error(title, curriculum, classes, book=None):
    """The checks shared by create and update, on the values the book
    would end up with."""
    if curriculum.approval_status == 'rejected':
        return api_error('%s was rejected: choose another curriculum.' % curriculum.name, status=400,
                         code='curriculum_rejected')
    outside = classes - curriculum.class_ids if curriculum.class_ids else classes.browse()
    if outside:
        return api_error('%s is not assigned to %s.' % (', '.join(outside.mapped('display_name')), curriculum.name),
                         status=400, code='class_not_in_curriculum')
    domain = [('name', '=ilike', title), ('curriculum_id', '=', curriculum.id)]
    if book:
        domain.append(('id', '!=', book.id))
    if request.env['op.media'].sudo().with_context(active_test=False).search_count(domain, limit=1):
        return api_error('%s already has a smart book with this title.' % curriculum.name, status=409,
                         code='smart_book_exists')
    return None


# -- Exams (bxi.exam.schedule: one exam across sections) ------------------------

EXAM_STATUSES = ('draft', 'partly_scheduled', 'scheduled', 'in_progress', 'done', 'cancelled')


def _exam_schedule_dict(schedule):
    sessions = schedule.sudo().session_ids.sorted(lambda s: (s.batch_id.display_name or '', s.id))
    papers = sessions.exam_ids.filtered(lambda e: e.state != 'cancel')
    live = sessions.filtered(lambda s: s.state != 'cancel')
    return {
        'id': schedule.id,
        'name': schedule.name,
        'start_date': date_str(schedule.start_date),
        'end_date': date_str(schedule.end_date),
        'exam_type': ref(schedule.exam_type_id),
        'status': schedule.state,
        'classes': [ref(b) for b in schedule.batch_ids],
        'section_ids': schedule.batch_ids.ids,
        'subjects': [ref(s) for s in schedule.subject_ids],
        'subject_ids': schedule.subject_ids.ids,
        'sessions': [{
            'id': session.id, 'section': ref(session.batch_id), 'class': ref(session.course_id),
            'exam_code': session.exam_code, 'state': session.state, 'papers': len(session.exam_ids),
        } for session in sessions],
        'papers_progress': {'set_up': len(papers), 'expected': len(live) * len(schedule.subject_ids)},
        'active': schedule.active,
    }


def _screen_date(payload, key):
    """(date or None when not sent, error): DD/MM/YYYY as on the screen, or
    YYYY-MM-DD."""
    if key not in payload:
        return None, None
    value = payload[key]
    if _blank(value):
        return None, api_error('%s is required.' % key, status=400, code='missing_%s' % key)
    if isinstance(value, str) and '/' in value:
        try:
            return datetime.datetime.strptime(value.strip(), '%d/%m/%Y').date(), None
        except ValueError:
            return None, api_error('%s must be DD/MM/YYYY or YYYY-MM-DD.' % key, status=400,
                                   code='invalid_%s' % key)
    return parse_date(value, key)


def _chips(payload, model, key, current=None):
    """(records or None when not sent, error) for the Classes / Subjects
    chips: the whole list ("<key>_ids" or the typed "<key>s"), or on
    update "add_<key>_ids" / "remove_<key>_ids"."""
    records, error = _named_list(payload, model, key)
    if error or records is not None:
        return records, error
    if current is None:
        return None, None
    add_key, remove_key = 'add_%s_ids' % key, 'remove_%s_ids' % key
    if add_key not in payload and remove_key not in payload:
        return None, None
    added, error = resolve_records(request.env, model, payload.get(add_key) or [], add_key)
    if error:
        return None, error
    removed, error = resolve_records(request.env, model, payload.get(remove_key) or [], remove_key)
    if error:
        return None, error
    return (current | added) - removed, None


def _exam_atomic(func):
    """atomic(), reporting the schedule's own refusals with their codes."""
    def guarded():
        try:
            return func()
        except ExamScheduleError as exc:
            raise _Refused(api_error(exc.args[0], status=exc.status, code=exc.code))
    return _atomic(guarded)


def _mapping_dict(mapping):
    return {
        'id': mapping.id,
        'subject': ref(mapping.subject_id),
        'class': ref(mapping.class_id),
        'teacher': ref(mapping.teacher_id),
        'curriculum': ref(mapping.curriculum_id),
        'subject_id': mapping.subject_id.id,
        'class_id': mapping.class_id.id,
        'teacher_id': mapping.teacher_id.id,
        'curriculum_id': mapping.curriculum_id.id,
        'display_name': mapping.display_name,
    }


# key on the screen -> model; "<key>_id" or "<key>" (the name as typed).
MAPPING_FIELDS = (('subject', 'op.subject'), ('class', 'op.course'), ('teacher', 'op.faculty'),
                  ('curriculum', 'bxi.curriculum'))


def _mapping_value(payload, key, model):
    """(record, None when not sent, or error) for one Add / Edit Subject
    Mapping field. A blank value comes back as an empty recordset."""
    id_key = '%s_id' % key
    if id_key in payload:
        # An archived teacher is found too, to say so (teacher_inactive).
        return resolve_record(request.env, model, payload[id_key], id_key)
    if key in payload and model != 'bxi.curriculum':
        name = payload[key]
        if _blank(name):
            return request.env[model].sudo(), None
        if not isinstance(name, str):
            return None, api_error('%s must be a name.' % key, status=400, code='invalid_%s' % key)
        return _match_name(model, name.strip(), key, id_key)
    return None, None


def _mapping_error(subject, course, teacher, curriculum, mapping=None):
    """The checks shared by create and update, on the values the mapping
    would end up with."""
    if not teacher.active:
        return api_error('%s is archived.' % teacher.name, status=400, code='teacher_inactive')
    if curriculum.approval_status == 'rejected':
        return api_error('%s was rejected: choose another curriculum.' % curriculum.name, status=400,
                         code='curriculum_rejected')
    if curriculum.class_ids and course not in curriculum.class_ids:
        return api_error('%s is not assigned to %s.' % (course.display_name, curriculum.name), status=400,
                         code='class_not_in_curriculum')
    if course.subject_ids and subject not in course.subject_ids:
        return api_error('%s is not a subject of %s.' % (subject.display_name, course.display_name), status=400,
                         code='subject_not_in_class')
    domain = [('subject_id', '=', subject.id), ('class_id', '=', course.id), ('curriculum_id', '=', curriculum.id)]
    if mapping:
        domain.append(('id', '!=', mapping.id))
    existing = request.env['bxi.subject.mapping'].sudo().with_context(active_test=False).search(domain, limit=1)
    if existing:
        return request.make_json_response({'success': False, 'error': {
            'message': '%s is already mapped for %s in %s (to %s).' % (
                subject.display_name, course.display_name, curriculum.name, existing.teacher_id.name),
            'code': 'mapping_exists', 'existing_mapping_id': existing.id}}, status=409)
    return None


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
        # ?status=approved fills the Add Smart Book screen's Curriculum dropdown.
        domain = []
        status = kwargs.get('status')
        if status:
            if status not in CURRICULUM_STATUSES:
                return api_error('status must be one of %s.' % ', '.join(CURRICULUM_STATUSES), status=400,
                                 code='invalid_status')
            domain.append(('approval_status', '=', status))
        Curriculum = request.env['bxi.curriculum'].sudo()
        total = Curriculum.search_count(domain)
        curricula = Curriculum.search(domain, limit=limit, offset=offset, order='id desc')
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

    # -- Smart Books -----------------------------------------------------------

    def _smart_book(self, book_id):
        book = request.env['op.media'].sudo().browse(book_id).exists()
        if not book or not book.curriculum_id:
            return None, api_error('Smart book not found.', status=404, code='not_found')
        return book, None

    def _smart_book_manager(self):
        if not _is_coordinator_or_manager(request.env.user):
            return api_error('Not authorized to manage smart books.', status=403, code='forbidden')
        return None

    def _locked_error(self):
        return api_error('This smart book is locked: unlock it first.', status=409, code='smart_book_locked')

    @http.route('/api/v1/academic/smart-books', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_smart_books(self, q=None, curriculum_id=None, class_id=None, subject_id=None, **kwargs):
        """The Smart Books Management screen: books mapped to a curriculum,
        filtered by "q" (title), curriculum_id, class_id and subject_id."""
        if not is_staff(request.env):
            return api_error('Not authorized to view smart books.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [('curriculum_id', '!=', False)]
        if q:
            domain.append(('name', 'ilike', q))
        for param, raw, field in (('curriculum_id', curriculum_id, 'curriculum_id'),
                                  ('class_id', class_id, 'course_ids'), ('subject_id', subject_id, 'subject_ids')):
            if raw:
                value, error = parse_int(raw, param)
                if error:
                    return error
                domain.append((field, 'in', [value]))
        Media = request.env['op.media'].sudo()
        total = Media.search_count(domain)
        books = Media.search(domain, limit=limit, offset=offset, order='name, id')
        return api_response({'smart_books': [_smart_book_dict(b) for b in books]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/academic/smart-books/<int:book_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_smart_book(self, book_id, **kwargs):
        if not is_staff(request.env):
            return api_error('Not authorized to view smart books.', status=403, code='forbidden')
        book, error = self._smart_book(book_id)
        if error:
            return error
        return api_response(_smart_book_dict(book))

    @http.route('/api/v1/academic/smart-books', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_smart_book(self, **kwargs):
        """The Add Smart Book screen - all four fields required: "title",
        "subject_ids" or "subjects" (names as typed), "class_ids" or
        "classes" (names as typed), "curriculum_id". Academic coordinators
        and managers."""
        error = self._smart_book_manager()
        if error:
            return error
        payload = json_body() or {}
        if 'title' not in payload:
            return api_error('title is required.', status=400, code='missing_title')
        title, error = _text(payload, 'title')
        if error:
            return error
        subjects, error = _named_list(payload, 'op.subject', 'subject')
        if error:
            return error
        if not subjects:
            return api_error('subject_ids is required.', status=400, code='missing_subject_ids')
        classes, error = _named_list(payload, 'op.course', 'class')
        if error:
            return error
        if not classes:
            return api_error('class_ids is required.', status=400, code='missing_class_ids')
        if payload.get('curriculum_id') in (None, ''):
            return api_error('curriculum_id is required.', status=400, code='missing_curriculum_id')
        curriculum, error = resolve_record(request.env, 'bxi.curriculum', payload['curriculum_id'], 'curriculum_id')
        if error:
            return error
        error = _smart_book_error(title, curriculum, classes)
        if error:
            return error
        book, error = atomic(lambda: request.env['op.media'].sudo().create({
            'name': title, 'subject_ids': [(6, 0, subjects.ids)], 'course_ids': [(6, 0, classes.ids)],
            'curriculum_id': curriculum.id}))
        if error:
            return error
        return api_response(_smart_book_dict(book), status=201)

    @http.route('/api/v1/academic/smart-books/<int:book_id>/update', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def update_smart_book(self, book_id, **kwargs):
        """The Edit Smart Book screen: any of the create fields; only the
        keys sent change. 409 smart_book_locked while locked."""
        error = self._smart_book_manager()
        if error:
            return error
        book, error = self._smart_book(book_id)
        if error:
            return error
        if book.bxi_locked:
            return self._locked_error()
        payload = json_body() or {}
        vals = {}
        title, error = _text(payload, 'title')
        if error:
            return error
        if title is not None:
            vals['name'] = title
        subjects, error = _named_list(payload, 'op.subject', 'subject')
        if error:
            return error
        if subjects is not None:
            if not subjects:
                return api_error('A smart book needs a subject.', status=400, code='missing_subject_ids')
            vals['subject_ids'] = [(6, 0, subjects.ids)]
        classes, error = _named_list(payload, 'op.course', 'class')
        if error:
            return error
        if classes is not None:
            if not classes:
                return api_error('A smart book needs a class.', status=400, code='missing_class_ids')
            vals['course_ids'] = [(6, 0, classes.ids)]
        curriculum = book.curriculum_id
        if 'curriculum_id' in payload:
            if payload['curriculum_id'] in (None, ''):
                return api_error('A smart book needs a curriculum.', status=400, code='missing_curriculum_id')
            curriculum, error = resolve_record(request.env, 'bxi.curriculum', payload['curriculum_id'],
                                               'curriculum_id')
            if error:
                return error
            vals['curriculum_id'] = curriculum.id
        if vals:
            error = _smart_book_error(title or book.name, curriculum,
                                      classes if classes is not None else book.course_ids, book)
            if error:
                return error
            _result, error = atomic(lambda: book.write(vals))
            if error:
                return error
        return api_response(_smart_book_dict(book))

    @http.route('/api/v1/academic/smart-books/<int:book_id>/toggle-lock', type='http', auth='public',
                methods=['POST'], csrf=False)
    @require_auth
    def toggle_lock_smart_book(self, book_id, **kwargs):
        error = self._smart_book_manager()
        if error:
            return error
        book, error = self._smart_book(book_id)
        if error:
            return error
        book.action_bxi_toggle_lock()
        return api_response(_smart_book_dict(book))

    @http.route('/api/v1/academic/smart-books/<int:book_id>/delete', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def delete_smart_book(self, book_id, **kwargs):
        """Deletes the book - or, when it has ever been issued or
        reserved, archives it so the library history stays."""
        error = self._smart_book_manager()
        if error:
            return error
        book, error = self._smart_book(book_id)
        if error:
            return error
        if book.bxi_locked:
            return self._locked_error()
        book = book.with_context(active_test=False)
        has_history = bool(book.movement_line or book.queue_ids)

        def remove():
            if has_history:
                book.active = False
            else:
                book.unit_ids.unlink()
                book.unlink()
            return True

        _result, error = atomic(remove)
        if error:
            return error
        return api_response({'id': book_id, 'deleted': not has_history, 'archived': has_history})

    # -- Exams -----------------------------------------------------------------

    def _exam_schedule(self, schedule_id):
        schedule = request.env['bxi.exam.schedule'].sudo().browse(schedule_id).exists()
        if not schedule:
            return None, api_error('Exam not found.', status=404, code='not_found')
        return schedule, None

    def _exam_forbidden(self):
        return api_error('Only exam staff can manage exams.', status=403, code='forbidden')

    def _exam_values(self, payload, schedule=None):
        """(vals, error) from the Add / Edit Exam body."""
        vals = {}
        name, error = _text(payload, 'name')
        if error:
            return None, error
        if name is not None:
            vals['name'] = name
        for key in ('start_date', 'end_date'):
            value, error = _screen_date(payload, key)
            if error:
                return None, error
            if value is not None:
                vals[key] = value
        for key, model, field in (('section', 'op.batch', 'batch_ids'), ('subject', 'op.subject', 'subject_ids')):
            records, error = _chips(payload, model, key, schedule[field] if schedule else None)
            if error:
                return None, error
            if records is not None:
                if not records:
                    return None, api_error('Add at least one %s.' % ('class' if key == 'section' else key),
                                           status=400, code='missing_%s_ids' % key)
                vals[field] = [(6, 0, records.ids)]
        if 'exam_type_id' in payload:
            exam_type, error = resolve_record(request.env, 'op.exam.type', payload['exam_type_id'], 'exam_type_id')
            if error:
                return None, error
            if exam_type:
                vals['exam_type_id'] = exam_type.id
        return vals, None

    @http.route('/api/v1/academic/exams', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_exams(self, q=None, status=None, date_from=None, date_to=None, **kwargs):
        """Filters: q (name), class_id, section_id, subject_id, status,
        date_from / date_to (exams overlapping that range)."""
        if not _is_exam_staff(request.env.user):
            return self._exam_forbidden()
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = []
        if q:
            domain.append(('name', 'ilike', q))
        for param, field in (('class_id', 'batch_ids.course_id'), ('section_id', 'batch_ids'),
                             ('subject_id', 'subject_ids')):
            if kwargs.get(param):
                value, error = parse_int(kwargs[param], param)
                if error:
                    return error
                domain.append((field, 'in', [value]))
        if status:
            if status not in EXAM_STATUSES:
                return api_error('status must be one of %s.' % ', '.join(EXAM_STATUSES), status=400,
                                 code='invalid_status')
            domain.append(('state', '=', status))
        for key, raw, operator, field in (('date_from', date_from, '>=', 'end_date'),
                                          ('date_to', date_to, '<=', 'start_date')):
            if raw:
                value, error = _screen_date({key: raw}, key)
                if error:
                    return error
                domain.append((field, operator, value))
        Schedule = request.env['bxi.exam.schedule'].sudo()
        total = Schedule.search_count(domain)
        schedules = Schedule.search(domain, limit=limit, offset=offset)
        return api_response({'exams': [_exam_schedule_dict(s) for s in schedules]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/academic/exams/<int:schedule_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_exam(self, schedule_id, **kwargs):
        if not _is_exam_staff(request.env.user):
            return self._exam_forbidden()
        schedule, error = self._exam_schedule(schedule_id)
        if error:
            return error
        return api_response(_exam_schedule_dict(schedule))

    @http.route('/api/v1/academic/exams', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_exam(self, **kwargs):
        """The Add Exam screen: "name", "start_date", "end_date"
        (DD/MM/YYYY or YYYY-MM-DD), "section_ids" or "sections" (as typed),
        "subject_ids" or "subjects", "exam_type_id"? (default General). A
        draft exam session is created for each section, ready for papers."""
        if not _is_exam_staff(request.env.user):
            return self._exam_forbidden()
        payload = json_body() or {}
        for key in ('name', 'start_date', 'end_date'):
            if key not in payload:
                return api_error('%s is required.' % key, status=400, code='missing_%s' % key)
        vals, error = self._exam_values(payload)
        if error:
            return error
        for field, key in (('batch_ids', 'section_ids'), ('subject_ids', 'subject_ids')):
            if field not in vals:
                return api_error('%s is required.' % key, status=400, code='missing_%s' % key)
        schedule, error = _exam_atomic(lambda: request.env['bxi.exam.schedule'].sudo().create(vals))
        if error:
            return error
        return api_response(_exam_schedule_dict(schedule), status=201)

    @http.route('/api/v1/academic/exams/<int:schedule_id>/update', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def update_exam(self, schedule_id, **kwargs):
        """The Edit Exam screen: any create key, or add_section_ids /
        remove_section_ids and add_subject_ids / remove_subject_ids for the
        chips. Only the keys sent change."""
        if not _is_exam_staff(request.env.user):
            return self._exam_forbidden()
        schedule, error = self._exam_schedule(schedule_id)
        if error:
            return error
        vals, error = self._exam_values(json_body() or {}, schedule)
        if error:
            return error
        if vals:
            _result, error = _exam_atomic(lambda: schedule.write(vals))
            if error:
                return error
        return api_response(_exam_schedule_dict(schedule))

    @http.route('/api/v1/academic/exams/<int:schedule_id>/delete', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def delete_exam(self, schedule_id, **kwargs):
        """Only before any paper is set up or section scheduled (409
        exam_in_progress): cancel its sessions instead."""
        if not _is_exam_staff(request.env.user):
            return self._exam_forbidden()
        schedule, error = self._exam_schedule(schedule_id)
        if error:
            return error
        _result, error = _exam_atomic(schedule.unlink)
        if error:
            return error
        return api_response({'id': schedule_id, 'deleted': True})

    @http.route('/api/v1/academic/subject-mappings', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_subject_mappings(self, q=None, **kwargs):
        """Filters: class_id, teacher_id, subject_id, curriculum_id and "q"
        (subject, class or teacher name)."""
        # Staff directory data; families aren't shown it, as with other staff lists.
        if not request.env.user.has_group('base.group_user'):
            return api_error('Not authorized to view subject mappings.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = []
        for param in ('class_id', 'teacher_id', 'subject_id', 'curriculum_id'):
            if kwargs.get(param):
                value, error = parse_int(kwargs[param], param)
                if error:
                    return error
                domain.append((param, '=', value))
        if q:
            domain += ['|', '|', ('subject_id.name', 'ilike', q), ('class_id.name', 'ilike', q),
                       ('teacher_id.name', 'ilike', q)]
        Mapping = request.env['bxi.subject.mapping'].sudo()
        total = Mapping.search_count(domain)
        mappings = Mapping.search(domain, limit=limit, offset=offset, order='id desc')
        return api_response(
            {'mappings': [_mapping_dict(m) for m in mappings]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    def _mapping(self, mapping_id):
        mapping = request.env['bxi.subject.mapping'].sudo().browse(mapping_id).exists()
        if not mapping:
            return None, api_error('Subject mapping not found.', status=404, code='not_found')
        return mapping, None

    def _mapping_manager(self):
        if not _is_coordinator_or_manager(request.env.user):
            return api_error('Not authorized to manage subject mappings.', status=403, code='forbidden')
        return None

    @http.route('/api/v1/academic/subject-mappings/<int:mapping_id>', type='http', auth='public', methods=['GET'],
                csrf=False)
    @require_auth
    def get_subject_mapping(self, mapping_id, **kwargs):
        if not request.env.user.has_group('base.group_user'):
            return api_error('Not authorized to view subject mappings.', status=403, code='forbidden')
        mapping, error = self._mapping(mapping_id)
        if error:
            return error
        return api_response(_mapping_dict(mapping))

    @http.route('/api/v1/academic/subject-mappings', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_subject_mapping(self, **kwargs):
        """The Add Subject Mapping screen - all required: "subject_id" or
        "subject" (name as typed), "class_id" or "class", "teacher_id" or
        "teacher" ("Dr. Sarah Johnson" - a title is ignored),
        "curriculum_id". Academic coordinators and managers. 409
        mapping_exists (with existing_mapping_id) when the subject is
        already mapped for that class and curriculum."""
        error = self._mapping_manager()
        if error:
            return error
        payload = json_body() or {}
        values = {}
        for key, model in MAPPING_FIELDS:
            record, error = _mapping_value(payload, key, model)
            if error:
                return error
            if not record:
                return api_error('%s_id is required.' % key, status=400, code='missing_%s_id' % key)
            values[key] = record
        error = _mapping_error(values['subject'], values['class'], values['teacher'], values['curriculum'])
        if error:
            return error
        mapping, error = atomic(lambda: request.env['bxi.subject.mapping'].sudo().create({
            'subject_id': values['subject'].id, 'class_id': values['class'].id,
            'teacher_id': values['teacher'].id, 'curriculum_id': values['curriculum'].id}))
        if error:
            return error
        return api_response(_mapping_dict(mapping), status=201)

    @http.route('/api/v1/academic/subject-mappings/<int:mapping_id>/update', type='http', auth='public',
                methods=['POST'], csrf=False)
    @require_auth
    def update_subject_mapping(self, mapping_id, **kwargs):
        """The Edit Subject Mapping screen: any of the create keys; only
        the keys sent change. Same checks as create."""
        error = self._mapping_manager()
        if error:
            return error
        mapping, error = self._mapping(mapping_id)
        if error:
            return error
        payload = json_body() or {}
        current = {'subject': mapping.subject_id, 'class': mapping.class_id, 'teacher': mapping.teacher_id,
                   'curriculum': mapping.curriculum_id}
        vals = {}
        for key, model in MAPPING_FIELDS:
            record, error = _mapping_value(payload, key, model)
            if error:
                return error
            if record is None:
                continue
            if not record:
                return api_error('%s_id is required.' % key, status=400, code='missing_%s_id' % key)
            current[key] = record
            vals['%s_id' % key] = record.id
        if vals:
            error = _mapping_error(current['subject'], current['class'], current['teacher'], current['curriculum'],
                                   mapping)
            if error:
                return error
            _result, error = atomic(lambda: mapping.write(vals))
            if error:
                return error
        return api_response(_mapping_dict(mapping))

    @http.route('/api/v1/academic/subject-mappings/<int:mapping_id>/delete', type='http', auth='public',
                methods=['POST'], csrf=False)
    @require_auth
    def delete_subject_mapping(self, mapping_id, **kwargs):
        error = self._mapping_manager()
        if error:
            return error
        mapping, error = self._mapping(mapping_id)
        if error:
            return error
        _result, error = atomic(mapping.unlink)
        if error:
            return error
        return api_response({'id': mapping_id, 'deleted': True})

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
