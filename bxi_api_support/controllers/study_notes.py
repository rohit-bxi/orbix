# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Study notes (bxi_student_learning) - the student app's Notes and Note
Details screens, and teachers publishing notes for their classes."""
from odoo import _, fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_file_response, api_response, parse_int, require_auth

from .academic import _is_coordinator_or_manager
from .common import (
    date_str, get_app_student, json_body, parse_pagination, ref, resolve_record, resolve_records, running_enrollment,
    school_context,
)
from .notice import _notice_dict, _visible_domain as visible_notices_domain
from .people_account import transaction
from .people_fields import _document_entries, apply_document_sets

PRIORITIES = ('normal', 'high')
TEXT_FIELDS = ('chapter', 'summary', 'key_points', 'content')


def _lines(text):
    return [line.strip() for line in (text or '').splitlines() if line.strip()]


def _attachment_list(attachments):
    return [{'id': a.id, 'name': a.name, 'mimetype': a.mimetype or None, 'size': a.file_size} for a in attachments]


def _note_dict(note, detail=False):
    user = request.env.user
    data = {
        'id': note.id,
        'title': note.name,
        'subject': ref(note.subject_id),
        'class': ref(note.course_id),
        'sections': [ref(b) for b in note.batch_ids],
        'teacher': ref(note.faculty_id),
        'chapter': note.chapter or None,
        'priority': note.priority,
        'tags': [t.name for t in note.tag_ids],
        'summary': note.summary or None,
        'key_points': _lines(note.key_points),
        'read_minutes': note.read_minutes,
        'publish_date': date_str(note.publish_date),
        'updated_at': date_str(note.write_date),
        'state': note.state,
        'comment_count': note.comment_count,
        'attachment_count': len(note.attachment_ids),
        'bookmarked': user in note.bookmark_user_ids,
    }
    if detail:
        related = request.env['bxi.study.note'].sudo().search([
            ('id', '!=', note.id), ('state', '=', 'published'), ('subject_id', '=', note.subject_id.id),
            ('course_id', '=', note.course_id.id)], limit=3)
        data.update({
            'content': note.content or None,
            'attachments': _attachment_list(note.attachment_ids),
            'related': [{'id': r.id, 'title': r.name, 'chapter': r.chapter or None, 'read_minutes': r.read_minutes}
                        for r in related],
        })
    return data


def _comment_dict(comment):
    user = request.env.user
    return {
        'id': comment.id,
        'author': {'id': comment.author_id.id, 'name': comment.author_id.name},
        'body': comment.body,
        'created_at': date_str(comment.create_date),
        'parent_id': comment.parent_id.id or None,
        'likes': len(comment.like_user_ids),
        'liked': user in comment.like_user_ids,
        'replies': [_comment_dict(r) for r in comment.reply_ids.filtered(lambda r: not r.hidden).sorted('id')],
    }


def _can_edit(env, note):
    context = school_context(env)
    return _is_coordinator_or_manager(env.user) or (context['faculty'] and note.faculty_id == context['faculty'])


def _note_vals(payload, note=None):
    """(vals, files, error) from a teacher's create / update body."""
    env = request.env
    vals = {}
    if 'title' in payload:
        if not isinstance(payload['title'], str) or not payload['title'].strip():
            return None, None, api_error('title is required.', status=400, code='missing_title')
        vals['name'] = payload['title'].strip()
    for key, model, field in (('subject_id', 'op.subject', 'subject_id'), ('class_id', 'op.course', 'course_id')):
        if key in payload:
            record, error = resolve_record(env, model, payload[key], key)
            if error:
                return None, None, error
            if not record:
                return None, None, api_error('%s is required.' % key, status=400, code='missing_%s' % key)
            vals[field] = record.id
    if 'section_ids' in payload:
        sections, error = resolve_records(env, 'op.batch', payload['section_ids'] or [], 'section_ids')
        if error:
            return None, None, error
        course_id = vals.get('course_id') or (note.course_id.id if note else None)
        if sections.filtered(lambda b: b.course_id.id != course_id):
            return None, None, api_error('Every section must belong to the class.', status=400,
                                         code='section_not_in_class')
        vals['batch_ids'] = [(6, 0, sections.ids)]
    for key in TEXT_FIELDS:
        if key in payload:
            value = payload[key]
            if isinstance(value, list) and key == 'key_points':
                value = '\n'.join(str(v) for v in value)
            vals[key] = value or False
    if 'priority' in payload:
        if payload['priority'] not in PRIORITIES:
            return None, None, api_error('priority must be normal or high.', status=400, code='invalid_priority')
        vals['priority'] = payload['priority']
    if 'tags' in payload:
        Tag = env['bxi.study.note.tag'].sudo()
        tags = Tag
        for name in payload['tags'] or []:
            name = str(name or '').strip()
            if name:
                tags |= Tag.search([('name', '=ilike', name)], limit=1) or Tag.create({'name': name})
        vals['tag_ids'] = [(6, 0, tags.ids)]
    files = None
    if 'attachments' in payload:
        files, error = _document_entries(payload['attachments'], 'attachments', 'attachments', 10 * 1024 * 1024)
        if error:
            return None, None, error
    return vals, files, None


class BxiApiSupportStudyNotesController(http.Controller):

    def _note(self, note_id, for_edit=False):
        env = request.env
        note = env['bxi.study.note'].sudo().browse(note_id).exists()
        if not note:
            return None, api_error('Note not found.', status=404, code='not_found')
        if for_edit:
            if not _can_edit(env, note):
                return None, api_error('Only the note\'s teacher or a coordinator can change it.', status=403,
                                       code='forbidden')
            return note, None
        if _can_edit(env, note) or school_context(env)['faculty']:
            return note, None
        for student in school_context(env)['students']:
            enrollment = running_enrollment(student)
            if enrollment and note in env['bxi.study.note'].sudo().search(
                    note._bxi_student_domain(enrollment) + [('id', '=', note.id)]):
                return note, None
        return None, api_error('Note not found.', status=404, code='not_found')

    # -- students -------------------------------------------------------------

    @http.route('/api/v1/notes', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_notes(self, student_id=None, subject_id=None, q=None, bookmarked=None, state=None, **kwargs):
        """Student (or a parent's child): the Notes screen - `subjects` (the
        chips, with counts), `announcement` (the latest pinned notice),
        `today` (published today) and `recent` (the rest, paginated);
        ?subject_id, ?q, ?bookmarked=1. Teacher: their own notes
        (coordinators: all), ?state=draft|published."""
        env = request.env
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Note = env['bxi.study.note'].sudo()
        context = school_context(env)
        filters = []
        if subject_id:
            value, error = parse_int(subject_id, 'subject_id')
            if error:
                return error
            filters.append(('subject_id', '=', value))
        if q:
            filters += ['|', ('name', 'ilike', q), ('summary', 'ilike', q)]
        if bookmarked in ('1', 'true', 'True'):
            filters.append(('bookmark_user_ids', 'in', env.user.id))

        if student_id or (context['students'] and not context['faculty']):
            student, error = get_app_student(env, student_id)
            if error:
                return error
            enrollment = running_enrollment(student)
            if not enrollment:
                return api_response({'subjects': [], 'announcement': None, 'today': [], 'recent': []},
                                    meta={'total': 0, 'limit': limit, 'offset': offset})
            visible = Note._bxi_student_domain(enrollment)
            subjects = {}
            for note in Note.search(visible):
                entry = subjects.setdefault(note.subject_id.id, {'id': note.subject_id.id,
                                                                 'name': note.subject_id.name, 'count': 0})
                entry['count'] += 1
            notes = Note.search(visible + filters)
            today = fields.Date.context_today(Note)
            todays = notes.filtered(lambda n: n.publish_date
                                    and fields.Datetime.context_timestamp(n, n.publish_date).date() == today)
            rest = notes - todays
            notice = env['bxi.notice'].sudo().search(visible_notices_domain(env), order='is_pinned desc, id desc',
                                                     limit=1) if 'bxi.notice' in env else None
            return api_response({
                'subjects': sorted(subjects.values(), key=lambda s: s['name'] or ''),
                'announcement': _notice_dict(notice) if notice else None,
                'today': [_note_dict(n) for n in todays],
                'recent': [_note_dict(n) for n in rest[offset:offset + limit]],
            }, meta={'total': len(rest), 'limit': limit, 'offset': offset})

        if not (context['faculty'] or _is_coordinator_or_manager(env.user)):
            return api_error('student_id is required.', status=400, code='missing_student_id')
        domain = list(filters)
        if not _is_coordinator_or_manager(env.user):
            domain.append(('faculty_id', '=', context['faculty'].id))
        if state:
            domain.append(('state', '=', state))
        total = Note.search_count(domain)
        notes = Note.search(domain, limit=limit, offset=offset)
        return api_response({'notes': [_note_dict(n) for n in notes]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/notes/<int:note_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_note(self, note_id, **kwargs):
        note, error = self._note(note_id)
        if error:
            return error
        return api_response(_note_dict(note, detail=True))

    @http.route('/api/v1/notes/<int:note_id>/pdf', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def note_pdf(self, note_id, **kwargs):
        """The Note Details screen's "Download PDF"."""
        note, error = self._note(note_id)
        if error:
            return error
        pdf, _type = request.env['ir.actions.report'].sudo()._render_qweb_pdf(
            'bxi_student_learning.action_report_study_note', note.ids)
        return api_file_response(pdf, 'Note - %s.pdf' % note.name)

    @http.route('/api/v1/notes/<int:note_id>/attachments/<int:attachment_id>', type='http', auth='public',
                methods=['GET'], csrf=False)
    @require_auth
    def note_attachment(self, note_id, attachment_id, **kwargs):
        note, error = self._note(note_id)
        if error:
            return error
        attachment = note.attachment_ids.filtered(lambda a: a.id == attachment_id)
        if not attachment:
            return api_error('Attachment not found.', status=404, code='not_found')
        return api_file_response(attachment.raw, attachment.name, attachment.mimetype or 'application/octet-stream')

    @http.route('/api/v1/notes/<int:note_id>/bookmark', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def bookmark(self, note_id, **kwargs):
        """{"bookmarked": true|false}; without it, toggles."""
        note, error = self._note(note_id)
        if error:
            return error
        payload = json_body() or {}
        user = request.env.user
        wanted = payload['bookmarked'] if 'bookmarked' in payload else user not in note.bookmark_user_ids
        note.bookmark_user_ids = [(4 if wanted else 3, user.id)]
        return api_response({'id': note.id, 'bookmarked': bool(wanted)})

    @http.route('/api/v1/notes/<int:note_id>/comments', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def comments(self, note_id, **kwargs):
        note, error = self._note(note_id)
        if error:
            return error
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        top = note.comment_ids.filtered(lambda c: not c.hidden and not c.parent_id)
        return api_response({'comments': [_comment_dict(c) for c in top[offset:offset + limit]]},
                            meta={'total': len(top), 'limit': limit, 'offset': offset})

    @http.route('/api/v1/notes/<int:note_id>/comments', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def add_comment(self, note_id, **kwargs):
        """{"body", "parent_id"? (reply)}"""
        note, error = self._note(note_id)
        if error:
            return error
        payload = json_body() or {}
        body = payload.get('body')
        if not isinstance(body, str) or not body.strip():
            return api_error('body is required.', status=400, code='missing_body')
        vals = {'note_id': note.id, 'author_id': request.env.user.id, 'body': body.strip()[:2000]}
        if payload.get('parent_id'):
            parent_id, error = parse_int(payload['parent_id'], 'parent_id')
            if error:
                return error
            parent = note.comment_ids.filtered(lambda c: c.id == parent_id and not c.hidden)
            if not parent:
                return api_error('parent_id is not a comment of this note.', status=400, code='invalid_parent_id')
            vals['parent_id'] = parent.id
        comment = request.env['bxi.study.note.comment'].sudo().create(vals)
        return api_response(_comment_dict(comment), status=201)

    @http.route('/api/v1/notes/comments/<int:comment_id>/like', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def like_comment(self, comment_id, **kwargs):
        comment = request.env['bxi.study.note.comment'].sudo().browse(comment_id).exists()
        if not comment or comment.hidden:
            return api_error('Comment not found.', status=404, code='not_found')
        _note, error = self._note(comment.note_id.id)
        if error:
            return error
        user = request.env.user
        comment.like_user_ids = [(3 if user in comment.like_user_ids else 4, user.id)]
        return api_response(_comment_dict(comment))

    # -- teachers -------------------------------------------------------------

    @http.route('/api/v1/notes', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_note(self, **kwargs):
        """Teachers (their own) and coordinators: {"title", "subject_id",
        "class_id", "section_ids"?, "chapter"?, "priority"?, "tags"?,
        "summary"?, "key_points"? (list or lines), "content"? (HTML),
        "attachments"? [base64 | {data, filename}], "publish"? (default
        true - students of the class are notified)}."""
        env = request.env
        context = school_context(env)
        coordinator = _is_coordinator_or_manager(env.user)
        if not (context['faculty'] or coordinator):
            return api_error('Only teachers and coordinators can publish notes.', status=403, code='forbidden')
        payload = json_body() or {}
        for key in ('title', 'subject_id', 'class_id'):
            if not payload.get(key):
                return api_error('%s is required.' % key, status=400, code='missing_%s' % key)
        vals, files, error = _note_vals(payload)
        if error:
            return error
        if coordinator and payload.get('teacher_id'):
            teacher, error = resolve_record(env, 'op.faculty', payload['teacher_id'], 'teacher_id')
            if error:
                return error
            vals['faculty_id'] = teacher.id
        elif context['faculty']:
            vals['faculty_id'] = context['faculty'].id
        else:
            return api_error('teacher_id is required.', status=400, code='missing_teacher_id')

        def create():
            note = env['bxi.study.note'].sudo().create(vals)
            if files:
                apply_document_sets(note, {'attachment_ids': files})
            if payload.get('publish', True):
                note.action_publish()
                self._announce(note)
            return note

        note, error = transaction(create)
        if error:
            return error
        return api_response(_note_dict(note, detail=True), status=201)

    @http.route('/api/v1/notes/<int:note_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_note(self, note_id, **kwargs):
        """Any create key; "attachments" is the whole list (ids to keep plus
        new files); "publish": true / false publishes or unpublishes."""
        note, error = self._note(note_id, for_edit=True)
        if error:
            return error
        payload = json_body() or {}
        vals, files, error = _note_vals(payload, note)
        if error:
            return error

        def write():
            was_published = note.state == 'published'
            if vals:
                note.write(vals)
            if files is not None:
                apply_document_sets(note, {'attachment_ids': files})
            if payload.get('publish') is True and not was_published:
                note.action_publish()
                self._announce(note)
            elif payload.get('publish') is False:
                note.action_unpublish()
            return True

        _result, error = transaction(write)
        if error:
            return error
        return api_response(_note_dict(note, detail=True))

    @http.route('/api/v1/notes/<int:note_id>/delete', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def delete_note(self, note_id, **kwargs):
        note, error = self._note(note_id, for_edit=True)
        if error:
            return error
        note.active = False
        return api_response({'id': note_id, 'deleted': True})

    @staticmethod
    def _announce(note):
        """Tell the class (or its chosen sections) a note was published."""
        domain = [('course_id', '=', note.course_id.id), ('state', '=', 'running')]
        if note.batch_ids:
            domain.append(('batch_id', 'in', note.batch_ids.ids))
        students = request.env['op.student.course'].sudo().search(domain).student_id
        request.env['bxi.notification'].sudo()._notify(
            students._bxi_family_users(), _('New notes: %s', note.name),
            '%s - %s' % (note.subject_id.name, note.faculty_id.name), category='note', record=note)
