# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The student app's people-to-people parts (bxi_student_learning):
doubts a student asks their teacher ("Smart Doubt Buddy - Ask Your
Tutor") and the section's student community. Both stay inside the school:
doubts go to the student's own subject or class teacher, and community
posts only reach the student's own section, moderated by its teachers."""
from odoo import _, fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth

from .academic import _is_coordinator_or_manager
from .common import (
    date_str, get_app_student, json_body, parse_pagination, ref, resolve_record, running_enrollment, school_context,
)
from .people_account import transaction
from .people_fields import _document_entries, apply_document_sets

POST_KINDS = ('discussion', 'notes', 'question')
MAX_TEXT = 4000


def _notify(users, title, body, category, record):
    request.env['bxi.notification'].sudo()._notify(users, title, body, category=category, record=record)


def _text(payload, key, required=True):
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        return None, api_error('%s is required.' % key, status=400, code='missing_%s' % key) if required else None
    return value.strip()[:MAX_TEXT], None


def _attachment_list(attachments):
    return [{'id': a.id, 'name': a.name, 'mimetype': a.mimetype or None} for a in attachments]


# -- doubts ---------------------------------------------------------------------------


def _doubt_dict(doubt):
    return {
        'id': doubt.id,
        'student': ref(doubt.student_id),
        'subject': ref(doubt.subject_id),
        'question': doubt.question,
        'attachments': _attachment_list(doubt.attachment_ids),
        'teacher': ref(doubt.teacher_id),
        'state': doubt.state,
        'answer': doubt.answer or None,
        'answered_by': ref(doubt.answered_by_id),
        'answered_at': date_str(doubt.answered_at),
        'asked_at': date_str(doubt.create_date),
    }


def _doubt_counts(doubts):
    today = fields.Date.context_today(doubts)
    return {
        'open': len(doubts.filtered(lambda d: d.state == 'open')),
        'answered': len(doubts.filtered(lambda d: d.state in ('answered', 'closed'))),
        'solved_today': len(doubts.filtered(
            lambda d: d.answered_at and fields.Datetime.context_timestamp(d, d.answered_at).date() == today)),
    }


# -- community ------------------------------------------------------------------------


def _post_dict(post, detail=False):
    user = request.env.user
    replies = post.reply_ids.filtered(lambda r: r.state == 'visible')
    data = {
        'id': post.id,
        'kind': post.kind,
        'title': post.title,
        'body': post.body or None,
        'author': {'id': post.author_id.id, 'name': post.author_id.name},
        'student': ref(post.student_id),
        'section': ref(post.batch_id),
        'created_at': date_str(post.create_date),
        'reply_count': len(replies),
        'likes': len(post.like_user_ids),
        'liked': user in post.like_user_ids,
        'state': post.state,
        'attachments': _attachment_list(post.attachment_ids),
    }
    if detail:
        data['replies'] = [{
            'id': r.id, 'author': {'id': r.author_id.id, 'name': r.author_id.name}, 'body': r.body,
            'created_at': date_str(r.create_date),
        } for r in replies]
    return data


class BxiApiSupportStudentSocialController(http.Controller):

    # -- doubts ----------------------------------------------------------------

    def _doubt(self, doubt_id):
        env = request.env
        doubt = env['bxi.student.doubt'].sudo().browse(doubt_id).exists()
        if not doubt:
            return None, None, api_error('Doubt not found.', status=404, code='not_found')
        context = school_context(env)
        if doubt.student_id in context['students']:
            return doubt, 'family', None
        if _is_coordinator_or_manager(env.user) or (context['faculty'] and doubt.teacher_id == context['faculty']):
            return doubt, 'teacher', None
        return None, None, api_error('Doubt not found.', status=404, code='not_found')

    @http.route('/api/v1/doubts', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_doubts(self, student_id=None, state=None, **kwargs):
        """Student (or parent): their doubts, newest first, with `counts`
        (open, answered, solved_today - the dashboard's "Solved Today").
        Teacher: the doubts assigned to them (coordinators: all);
        ?state=open|answered|closed."""
        env = request.env
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Doubt = env['bxi.student.doubt'].sudo()
        context = school_context(env)
        if student_id or (context['students'] and not context['faculty']):
            student, error = get_app_student(env, student_id)
            if error:
                return error
            domain = [('student_id', '=', student.id)]
        elif _is_coordinator_or_manager(env.user):
            domain = []
        elif context['faculty']:
            domain = [('teacher_id', '=', context['faculty'].id)]
        else:
            return api_error('student_id is required.', status=400, code='missing_student_id')
        counts = _doubt_counts(Doubt.search(domain))
        if state:
            domain = domain + [('state', '=', state)]
        total = Doubt.search_count(domain)
        doubts = Doubt.search(domain, limit=limit, offset=offset)
        return api_response({'doubts': [_doubt_dict(d) for d in doubts], 'counts': counts},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/doubts', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def ask(self, **kwargs):
        """The student's own question: {"question", "subject_id"?,
        "attachments"? [base64 | {data, filename}]}. It goes to the subject
        teacher of the class (Subject Mapping), else the class teacher."""
        env = request.env
        own = env['op.student'].sudo().search([('user_id', '=', env.user.id)], limit=1)
        if not own:
            return api_error('Only a student can ask a doubt.', status=403, code='forbidden')
        payload = json_body() or {}
        question, error = _text(payload, 'question')
        if error:
            return error
        subject, error = resolve_record(env, 'op.subject', payload.get('subject_id'), 'subject_id')
        if error:
            return error
        files = None
        if payload.get('attachments'):
            files, error = _document_entries(payload['attachments'], 'attachments', 'attachments', 5 * 1024 * 1024)
            if error:
                return error
        enrollment = running_enrollment(own)
        Doubt = env['bxi.student.doubt'].sudo()
        teacher = Doubt._bxi_teacher_for(enrollment, subject)

        def create():
            doubt = Doubt.create({
                'student_id': own.id, 'subject_id': subject.id or False, 'question': question,
                'course_id': enrollment.course_id.id or False, 'batch_id': enrollment.batch_id.id or False,
                'teacher_id': teacher.id or False})
            if files:
                apply_document_sets(doubt, {'attachment_ids': files})
            if teacher.user_id:
                _notify(teacher.user_id, _('New doubt from %s', own.name), question[:120], 'doubt', doubt)
            return doubt

        doubt, error = transaction(create)
        if error:
            return error
        return api_response(_doubt_dict(doubt), status=201)

    @http.route('/api/v1/doubts/<int:doubt_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_doubt(self, doubt_id, **kwargs):
        doubt, _role, error = self._doubt(doubt_id)
        if error:
            return error
        return api_response(_doubt_dict(doubt))

    @http.route('/api/v1/doubts/<int:doubt_id>/answer', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def answer(self, doubt_id, **kwargs):
        """The assigned teacher (or a coordinator): {"answer"}. The student
        and their parents are notified."""
        doubt, role, error = self._doubt(doubt_id)
        if error:
            return error
        if role != 'teacher':
            return api_error('Only the assigned teacher can answer.', status=403, code='forbidden')
        answer, error = _text(json_body() or {}, 'answer')
        if error:
            return error
        if doubt.state == 'closed':
            return api_error('This doubt is closed.', status=400, code='doubt_closed')
        doubt.action_answer(answer, request.env.user)
        _notify(doubt.student_id._bxi_family_users(), _('Your doubt was answered'), answer[:120], 'doubt', doubt)
        return api_response(_doubt_dict(doubt))

    # -- community -------------------------------------------------------------

    def _member_sections(self, student_id=None):
        """(sections the caller may read, student posting or None, is_moderator, error)."""
        env = request.env
        context = school_context(env)
        if _is_coordinator_or_manager(env.user):
            return None, None, True, None
        if context['faculty']:
            # Their timetable / class-teacher sections, plus every section of
            # the classes they teach a subject in (Subject Mapping).
            mapped = env['bxi.subject.mapping'].sudo().search([('teacher_id', '=', context['faculty'].id)]).class_id
            sections = context['teaching_batches'] | env['op.batch'].sudo().search([('course_id', 'in', mapped.ids)])
            return sections, None, True, None
        student, error = get_app_student(env, student_id)
        if error:
            return None, None, False, error
        enrollment = running_enrollment(student)
        if not enrollment:
            return None, None, False, api_error('The student is not in a section yet.', status=400,
                                                code='no_section')
        own = student if student.user_id == env.user else None
        return enrollment.batch_id, own, False, None

    def _post(self, post_id):
        """(post, sections, own student, moderator, error) when visible to the caller."""
        post = request.env['bxi.community.post'].sudo().browse(post_id).exists()
        sections, student, moderator, error = self._member_sections()
        if error:
            return None, None, None, False, error
        if not post or (sections is not None and post.batch_id not in sections) or (
                post.state == 'hidden' and not moderator):
            return None, None, None, False, api_error('Post not found.', status=404, code='not_found')
        return post, sections, student, moderator, None

    @http.route('/api/v1/community/posts', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_posts(self, student_id=None, section_id=None, kind=None, **kwargs):
        """The student's own section's posts, newest first (the dashboard's
        Student Community). Teachers: their sections (?section_id=);
        coordinators: any section. Moderators also see hidden posts."""
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        sections, _student, moderator, error = self._member_sections(student_id)
        if error:
            return error
        domain = [] if sections is None else [('batch_id', 'in', sections.ids)]
        if section_id:
            value, error = parse_int(section_id, 'section_id')
            if error:
                return error
            domain.append(('batch_id', '=', value))
        if kind:
            domain.append(('kind', '=', kind))
        if not moderator:
            domain.append(('state', '=', 'visible'))
        Post = request.env['bxi.community.post'].sudo()
        total = Post.search_count(domain)
        posts = Post.search(domain, limit=limit, offset=offset)
        return api_response({'posts': [_post_dict(p) for p in posts]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/community/posts', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_post(self, **kwargs):
        """A student's post to their own section: {"kind":
        discussion|notes|question, "title", "body"?, "attachments"?}."""
        sections, student, _moderator, error = self._member_sections()
        if error:
            return error
        if not student:
            return api_error('Only students post in the community.', status=403, code='forbidden')
        payload = json_body() or {}
        title, error = _text(payload, 'title')
        if error:
            return error
        kind = payload.get('kind') or 'discussion'
        if kind not in POST_KINDS:
            return api_error('kind must be one of %s.' % ', '.join(POST_KINDS), status=400, code='invalid_kind')
        body, _error = _text(payload, 'body', required=False)
        files = None
        if payload.get('attachments'):
            files, error = _document_entries(payload['attachments'], 'attachments', 'attachments', 5 * 1024 * 1024)
            if error:
                return error

        def create():
            post = request.env['bxi.community.post'].sudo().create({
                'student_id': student.id, 'author_id': request.env.user.id, 'batch_id': sections.id,
                'kind': kind, 'title': title[:200], 'body': body})
            if files:
                apply_document_sets(post, {'attachment_ids': files})
            return post

        post, error = transaction(create)
        if error:
            return error
        return api_response(_post_dict(post, detail=True), status=201)

    @http.route('/api/v1/community/posts/<int:post_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_post(self, post_id, **kwargs):
        post, _sections, _student, _moderator, error = self._post(post_id)
        if error:
            return error
        return api_response(_post_dict(post, detail=True))

    @http.route('/api/v1/community/posts/<int:post_id>/replies', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def reply(self, post_id, **kwargs):
        """{"body"} - students of the section and its teachers."""
        post, _sections, student, moderator, error = self._post(post_id)
        if error:
            return error
        if not (student or moderator):
            return api_error('Only students and teachers reply in the community.', status=403, code='forbidden')
        if post.state != 'visible':
            return api_error('This post is hidden.', status=400, code='post_hidden')
        body, error = _text(json_body() or {}, 'body')
        if error:
            return error
        request.env['bxi.community.reply'].sudo().create({
            'post_id': post.id, 'author_id': request.env.user.id, 'student_id': student.id if student else False,
            'body': body})
        if post.author_id != request.env.user:
            _notify(post.author_id, _('New reply: %s', post.title), body[:120], 'community', post)
        return api_response(_post_dict(post, detail=True), status=201)

    @http.route('/api/v1/community/posts/<int:post_id>/like', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def like(self, post_id, **kwargs):
        post, _sections, _student, _moderator, error = self._post(post_id)
        if error:
            return error
        user = request.env.user
        post.like_user_ids = [(3 if user in post.like_user_ids else 4, user.id)]
        return api_response(_post_dict(post))

    @http.route('/api/v1/community/posts/<int:post_id>/report', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def report(self, post_id, **kwargs):
        """{"reason"?}: once per person; three reports hide the post until
        a teacher reviews it."""
        post, _sections, _student, _moderator, error = self._post(post_id)
        if error:
            return error
        reason, _error = _text(json_body() or {}, 'reason', required=False)
        post._bxi_report(request.env.user, reason)
        return api_response({'id': post.id, 'reported': True, 'state': post.state})

    @http.route('/api/v1/community/posts/<int:post_id>/<any("hide", "unhide"):action>', type='http',
                auth='public', methods=['POST'], csrf=False)
    @require_auth
    def moderate(self, post_id, action, **kwargs):
        """The section's teachers and coordinators. Unhiding clears reports."""
        post, _sections, _student, moderator, error = self._post(post_id)
        if error:
            return error
        if not moderator:
            return api_error('Only teachers moderate the community.', status=403, code='forbidden')
        if action == 'hide':
            post.action_hide()
            reason, _error = _text(json_body() or {}, 'reason', required=False)
            if reason:
                post.hidden_reason = reason
        else:
            post.action_unhide()
        return api_response(_post_dict(post, detail=True))
