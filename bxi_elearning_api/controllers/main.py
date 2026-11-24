# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""eLearning for the Orbix app: the eLearning classes and sections, the
courses (slide.channel) the signed-in user may see, joining an open
course, its lessons (slide.slide) and marking them completed.

Every read runs as the signed-in user, so website_slides' own access rules
decide what is visible: published courses that are open to signed-in
users, plus members-only courses the user has joined or was invited to.
eLearning classes are their own master data - they are not linked to the
school's classes (op.course), so the app passes the eLearning class or
section it wants."""
import base64

from odoo import fields, http
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain
from odoo.http import request
from odoo.tools import html2plaintext
from odoo.tools.mimetypes import guess_mimetype

from odoo.addons.bxi_api.controllers.auth import (
    api_error, api_file_response, api_response, parse_int, require_auth,
)

MAX_LIMIT = 200


def _ref(record):
    return {'id': record.id, 'name': record.display_name} if record else None


def _pagination(kwargs):
    limit, offset = 50, 0
    if kwargs.get('limit') is not None:
        limit, error = parse_int(kwargs['limit'], 'limit')
        if error:
            return None, None, error
        limit = max(1, min(limit, MAX_LIMIT))
    if kwargs.get('offset') is not None:
        offset, error = parse_int(kwargs['offset'], 'offset')
        if error:
            return None, None, error
        offset = max(0, offset)
    return limit, offset, None


def _course_lessons(channel):
    """The course's published lessons (not section headers), in order. sudo
    keeps the caller's uid, so per-user completion still applies."""
    return request.env['slide.slide'].sudo().search(
        [('channel_id', '=', channel.id), ('website_published', '=', True), ('is_category', '=', False)],
        order='sequence, id')


def _reading(slide):
    """The caller's progress record on a lesson (website_slides keeps one
    per member and lesson), or an empty recordset."""
    return request.env['slide.slide.partner'].sudo().search(
        [('slide_id', '=', slide.id), ('partner_id', '=', request.env.user.partner_id.id)], limit=1)


def _progress(channel):
    """The Smart Books card: which chapter to continue ("Chapter 5 of 12")
    and how long is left. None for a course the user has not joined."""
    if not channel.is_member:
        return None
    lessons = _course_lessons(channel)
    pending = lessons.filtered(lambda slide: not slide.user_has_completed)
    current = pending[:1] or lessons[-1:]
    return {
        'chapter_index': list(lessons).index(current) + 1 if current else 0,
        'chapter_count': len(lessons),
        'current_lesson': {'id': current.id, 'name': current.name} if current else None,
        'hours_left': round(sum(pending.mapped('completion_time')), 2),
    }


def _course_dict(channel):
    return {
        'id': channel.id,
        'name': channel.name,
        'summary': channel.description_short or None,
        'class': _ref(channel.class_id),
        'section': _ref(channel.section_id),
        'tags': [t.name for t in channel.tag_ids],
        'enroll': channel.enroll,
        'visibility': channel.visibility,
        'lesson_count': channel.total_slides,
        'duration_hours': round(channel.total_time, 2),
        'is_member': channel.is_member,
        'is_invited': channel.is_member_invited,
        'can_join': not channel.is_member and channel.enroll == 'public',
        'completion': channel.completion if channel.is_member else None,
        'has_image': bool(channel.image_128),
        'progress': _progress(channel),
        'website_url': channel.website_url or None,
    }


def _lesson_dict(slide, content=False):
    data = {
        'id': slide.id,
        'name': slide.name,
        'category': slide.slide_category,
        'section': _ref(slide.category_id),
        'duration_hours': round(slide.completion_time, 2),
        'is_preview': slide.is_preview,
        'locked': not (slide.channel_id.is_member or slide.is_preview),
        'completed': slide.user_has_completed,
        'can_mark_completed': slide.can_self_mark_completed,
        'has_quiz': bool(slide.question_ids),
    }
    if content:
        reading = _reading(slide)
        lessons = _course_lessons(slide.channel_id)
        index = list(lessons).index(slide) if slide in lessons else -1
        data.update({
            'position': {
                'page': reading.bxi_page or 0, 'total_pages': reading.bxi_total_pages or 0,
                'percent': reading.bxi_percent or 0.0,
            } if reading else None,
            'previous_lesson': _ref(lessons[index - 1]) if index > 0 else None,
            'next_lesson': _ref(lessons[index + 1]) if 0 <= index < len(lessons) - 1 else None,
            'quiz_question_count': len(slide.question_ids),
            'description': slide.description or None,
            'url': slide.url or None,
            'html_content': slide.html_content or None if slide.slide_category == 'article' else None,
            'has_file': bool(slide.binary_content) or (slide.slide_category == 'infographic' and bool(slide.image_1920)),
            'website_url': slide.website_url or None,
        })
        data.update(_reader_dict(slide))
    return data


def _reader_dict(slide):
    """The reader screen: what Read / Listen / Watch can open, the plain
    text for the phone's text-to-speech, "15 min read", level, rating,
    learning objectives and the languages the chapter can be read in."""
    article = slide.slide_category == 'article' and bool(slide.html_content)
    video_url = slide.bxi_video_url or (slide.url if slide.slide_category == 'video' else None)
    read_minutes = slide.bxi_read_minutes or (round(slide.completion_time * 60) if slide.completion_time else None)
    channel = slide.channel_id.sudo()
    return {
        'language': slide.env.lang or 'en_US',
        'languages': [{'code': lang.code, 'name': lang.name}
                      for lang in slide.env['res.lang'].sudo().search([('active', '=', True)], order='name')],
        'read_minutes': read_minutes,
        'level': slide.bxi_level or None,
        'rating': round(channel.rating_avg_stars, 1) if channel.rating_count else None,
        'learning_objectives': [line.strip(' -•\t') for line in (slide.bxi_learning_objectives or '').splitlines()
                                if line.strip(' -•\t')],
        'modes': {
            'read': article or bool(slide.binary_content),
            'listen': {'available': article or bool(slide.bxi_audio), 'audio': bool(slide.bxi_audio),
                       'text_to_speech': article},
            'watch': {'available': bool(video_url), 'video_url': video_url or None},
        },
        'tts_text': html2plaintext(slide.html_content) if article else None,
    }


def _visible_courses():
    """The signed-in user's view of published courses."""
    return request.env['slide.channel'].with_context(active_test=True)


class BxiElearningApiController(http.Controller):

    def _course(self, channel_id):
        channel = _visible_courses().search(
            [('id', '=', channel_id), ('website_published', '=', True)], limit=1)
        if not channel:
            return None, api_error('Course not found.', status=404, code='not_found')
        return channel, None

    def _lesson(self, slide_id):
        """A published lesson of a course the user can open: as a member,
        or a preview lesson."""
        # Found with sudo (a members-only lesson is invisible to a
        # non-member), then only served when the caller can see its course.
        slide = request.env['slide.slide'].sudo().search(
            [('id', '=', slide_id), ('website_published', '=', True), ('is_category', '=', False)], limit=1)
        if not slide:
            return None, api_error('Lesson not found.', status=404, code='not_found')
        _channel, error = self._course(slide.channel_id.id)
        if error:
            return None, api_error('Lesson not found.', status=404, code='not_found')
        if not (slide.channel_id.is_member or slide.is_preview):
            return None, api_error('Join the course to open this lesson.', status=403, code='join_required')
        return slide, None

    @http.route('/api/v1/elearning/classes', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def classes(self, **kwargs):
        """eLearning classes with their sections and published course
        counts, for the app's filters."""
        courses = _visible_courses().search([('website_published', '=', True)])
        classes = request.env['elearning.class'].sudo().search([('website_published', '=', True)])
        return api_response({'classes': [{
            'id': c.id,
            'name': c.name,
            'course_count': len(courses.filtered(lambda ch, c=c: ch.class_id == c)),
            'sections': [{
                'id': s.id, 'name': s.name,
                'course_count': len(courses.filtered(lambda ch, s=s: ch.section_id == s)),
            } for s in c.section_ids.filtered('website_published')],
        } for c in classes]})

    @http.route('/api/v1/elearning/courses', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def courses(self, class_id=None, section_id=None, q=None, joined=None, tag_id=None, in_progress=None,
                **kwargs):
        """?class_id= / ?section_id= (eLearning ids), ?q= (name), ?joined=1
        (only courses the user has joined), ?tag_id= (the Smart Books
        subject chips), ?in_progress=1 ("Continue Reading": joined, started,
        not finished). Joined courses carry `progress`: chapter_index of
        chapter_count, current_lesson and hours_left."""
        limit, offset, error = _pagination(kwargs)
        if error:
            return error
        domain = Domain('website_published', '=', True)
        for param, value, field in (('class_id', class_id, 'class_id'), ('section_id', section_id, 'section_id')):
            if value:
                value, error = parse_int(value, param)
                if error:
                    return error
                domain &= Domain(field, '=', value)
        if q:
            domain &= Domain('name', 'ilike', q)
        if joined in ('1', 'true', 'True'):
            domain &= Domain('is_member', '=', True)
        if tag_id:
            value, error = parse_int(tag_id, 'tag_id')
            if error:
                return error
            domain &= Domain('tag_ids', 'in', [value])
        Channel = _visible_courses()
        if in_progress in ('1', 'true', 'True'):
            # completion is per user and not stored: filter after the search.
            started = Channel.search(domain & Domain('is_member', '=', True), order='sequence, name, id').filtered(
                lambda channel: 0 < channel.completion < 100)
            return api_response({'courses': [_course_dict(c) for c in started[offset:offset + limit]]},
                                meta={'total': len(started), 'limit': limit, 'offset': offset})
        channels = Channel.search(domain, limit=limit, offset=offset, order='sequence, name, id')
        return api_response({'courses': [_course_dict(c) for c in channels]},
                            meta={'total': Channel.search_count(domain), 'limit': limit, 'offset': offset})

    @http.route('/api/v1/elearning/courses/<int:channel_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def course(self, channel_id, **kwargs):
        """The course with its lessons in order, grouped by section, and the
        user's progress on each."""
        channel, error = self._course(channel_id)
        if error:
            return error
        # The outline is shown to everyone who can see the course, as on the
        # website; members-only lessons come back "locked". sudo keeps the
        # caller's uid, so per-user progress still reflects the caller.
        slides = request.env['slide.slide'].sudo().search(
            [('channel_id', '=', channel.id), ('website_published', '=', True)], order='sequence, id')
        data = _course_dict(channel)
        data['description'] = channel.description or None
        data['sections'] = []
        loose = [_lesson_dict(s) for s in slides if not s.is_category and not s.category_id]
        if loose:
            data['sections'].append({'id': None, 'name': None, 'lessons': loose})
        for category in slides.filtered('is_category'):
            data['sections'].append({
                'id': category.id,
                'name': category.name,
                'lessons': [_lesson_dict(s) for s in slides if not s.is_category and s.category_id == category],
            })
        return api_response(data)

    @http.route('/api/v1/elearning/courses/<int:channel_id>/join', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def join(self, channel_id, **kwargs):
        """Join an open course (or accept an invitation to one)."""
        channel, error = self._course(channel_id)
        if error:
            return error
        if channel.is_member:
            return api_response(_course_dict(channel))
        if channel.enroll != 'public' and not channel.is_member_invited:
            return api_error('This course is by invitation only.', status=403, code='invitation_only')
        try:
            if channel.enroll == 'public':
                channel._action_add_members(request.env.user.partner_id, raise_on_access=True)
            else:
                channel.sudo()._action_add_members(request.env.user.partner_id)
        except AccessError as exc:
            return api_error(str(exc), status=403, code='forbidden')
        channel.invalidate_recordset()
        return api_response(_course_dict(channel))

    @http.route('/api/v1/elearning/lessons/<int:slide_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def lesson(self, slide_id, lang=None, **kwargs):
        """A lesson's content. Opening it as a member records it as viewed.
        `lang` (e.g. hi_IN, one of the returned `languages`) reads the
        chapter's translation; untranslated text falls back to the original."""
        slide, error = self._lesson(slide_id)
        if error:
            return error
        if lang:
            if not request.env['res.lang'].sudo().search_count([('code', '=', lang), ('active', '=', True)]):
                return api_error('This language is not available.', status=400, code='invalid_language')
            slide = slide.with_context(lang=lang)
        if slide.channel_id.is_member:
            slide._action_set_viewed(request.env.user.partner_id)
        return api_response(dict(_lesson_dict(slide, content=True), course=_ref(slide.channel_id)))

    @http.route('/api/v1/elearning/lessons/<int:slide_id>/audio', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def lesson_audio(self, slide_id, **kwargs):
        """The chapter's uploaded narration for "Listen"."""
        slide, error = self._lesson(slide_id)
        if error:
            return error
        raw = slide.sudo().bxi_audio
        if not raw:
            return api_error('This lesson has no audio: use text_to_speech.', status=404, code='no_audio')
        content = base64.b64decode(raw)
        mimetype = guess_mimetype(content, default='audio/mpeg')
        if not mimetype.startswith('audio/'):
            mimetype = 'audio/mpeg'
        filename = slide.bxi_audio_filename or 'lesson-%s.mp3' % slide.id
        return api_file_response(content, filename, mimetype=mimetype)

    @http.route('/api/v1/elearning/lessons/<int:slide_id>/file', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def lesson_file(self, slide_id, **kwargs):
        """The lesson's document (PDF) or infographic image."""
        slide, error = self._lesson(slide_id)
        if error:
            return error
        raw = slide.sudo().binary_content or (slide.sudo().image_1920 if slide.slide_category == 'infographic' else False)
        if not raw:
            return api_error('This lesson has no file.', status=404, code='no_file')
        content = base64.b64decode(raw)
        mimetype = guess_mimetype(content, default='application/octet-stream')
        extension = {'application/pdf': 'pdf', 'image/png': 'png', 'image/jpeg': 'jpg'}.get(mimetype, 'bin')
        return api_file_response(content, f'lesson-{slide.id}.{extension}', mimetype=mimetype)

    @http.route('/api/v1/elearning/lessons/<int:slide_id>/complete', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def complete(self, slide_id, **kwargs):
        """Mark a lesson completed (members only; a quiz lesson completes by
        passing its quiz on the website)."""
        slide, error = self._lesson(slide_id)
        if error:
            return error
        if not slide.channel_id.is_member:
            return api_error('Join the course to track progress.', status=403, code='join_required')
        if not slide.user_has_completed:
            try:
                slide.action_mark_completed()
            except UserError as exc:
                return api_error(str(exc), status=400, code='cannot_complete')
        slide.invalidate_recordset()
        slide.channel_id.invalidate_recordset()
        return api_response(dict(_lesson_dict(slide), course=_course_dict(slide.channel_id)))

    @http.route('/api/v1/elearning/lessons/<int:slide_id>/position', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def position(self, slide_id, **kwargs):
        """Remember where the reader is in a lesson: {"page", "total_pages"}
        or {"percent"} (0-100). Members only."""
        slide, error = self._lesson(slide_id)
        if error:
            return error
        if not slide.channel_id.is_member:
            return api_error('Join the course to track progress.', status=403, code='join_required')
        payload = request.get_json_data() if request.httprequest.data else {}
        vals = {}
        for key, field in (('page', 'bxi_page'), ('total_pages', 'bxi_total_pages')):
            if key in payload:
                value, error = parse_int(payload[key], key)
                if error:
                    return error
                if value < 0:
                    return api_error(f'{key} cannot be negative.', status=400, code=f'invalid_{key}')
                vals[field] = value
        if 'percent' in payload:
            try:
                percent = float(payload['percent'])
            except (TypeError, ValueError):
                return api_error('percent must be a number.', status=400, code='invalid_percent')
            vals['bxi_percent'] = percent
        elif vals.get('bxi_total_pages'):
            vals['bxi_percent'] = 100.0 * vals.get('bxi_page', 0) / vals['bxi_total_pages']
        if not vals:
            return api_error('Send page and total_pages, or percent.', status=400, code='missing_position')
        if not 0 <= vals.get('bxi_percent', 0) <= 100 or vals.get('bxi_page', 0) > (
                vals.get('bxi_total_pages') or vals.get('bxi_page', 0)):
            return api_error('The position is outside the lesson.', status=400, code='invalid_position')
        reading = _reading(slide)
        if not reading:
            slide._action_set_viewed(request.env.user.partner_id)
            reading = _reading(slide)
        vals['bxi_position_date'] = fields.Datetime.now()
        reading.write(vals)
        return api_response(dict(_lesson_dict(slide, content=True), course=_ref(slide.channel_id)))

    @http.route('/api/v1/elearning/lessons/<int:slide_id>/quiz', type='http', auth='public', methods=['GET'],
                csrf=False)
    @require_auth
    def quiz(self, slide_id, **kwargs):
        """The lesson's quiz (the reader's "Quick Check"): questions and
        their answers. Which answer is correct is only shown once the
        lesson is completed."""
        slide, error = self._lesson(slide_id)
        if error:
            return error
        if not slide.question_ids:
            return api_error('This lesson has no quiz.', status=404, code='no_quiz')
        done = slide.user_has_completed
        reading = _reading(slide)
        return api_response({
            'lesson': _ref(slide),
            'completed': done,
            'attempts': reading.quiz_attempts_count if reading else 0,
            'questions': [{
                'id': question.id,
                'question': question.question,
                'answers': [{
                    'id': answer.id, 'text': answer.text_value,
                    'is_correct': answer.is_correct if done else None,
                } for answer in question.sudo().answer_ids.sorted(lambda a: (a.sequence, a.id))],
            } for question in slide.sudo().question_ids.sorted(lambda q: (q.sequence, q.id))],
        })

    @http.route('/api/v1/elearning/lessons/<int:slide_id>/quiz/submit', type='http', auth='public',
                methods=['POST'], csrf=False)
    @require_auth
    def quiz_submit(self, slide_id, **kwargs):
        """{"answer_ids": [one answer per question]}: scored as on the
        eLearning website - all correct completes the lesson; otherwise the
        student sees which answers were wrong and tries again. Members only."""
        slide, error = self._lesson(slide_id)
        if error:
            return error
        if not slide.channel_id.is_member:
            return api_error('Join the course to take its quizzes.', status=403, code='join_required')
        questions = slide.sudo().question_ids
        if not questions:
            return api_error('This lesson has no quiz.', status=404, code='no_quiz')
        if slide.user_has_completed:
            return api_error('This quiz is already passed.', status=409, code='quiz_done')
        payload = request.get_json_data() if request.httprequest.data else {}
        raw = payload.get('answer_ids')
        if not isinstance(raw, list):
            return api_error('answer_ids must be a list.', status=400, code='invalid_answer_ids')
        ids = []
        for value in raw:
            answer_id, error = parse_int(value, 'answer_ids')
            if error:
                return error
            ids.append(answer_id)
        answers = request.env['slide.answer'].sudo().browse(ids).exists()
        if len(answers) != len(set(ids)) or answers.question_id - questions:
            return api_error('Some answers are not part of this quiz.', status=400, code='invalid_answer_ids')
        if answers.question_id != questions or len(answers) != len(questions):
            return api_error('Answer every question, once each.', status=400, code='quiz_incomplete')
        slide._action_set_viewed(request.env.user.partner_id, quiz_attempts_inc=True)
        wrong = answers.filtered(lambda answer: not answer.is_correct)
        if not wrong:
            slide._action_mark_completed()
        slide.invalidate_recordset()
        slide.channel_id.invalidate_recordset()
        return api_response({
            'passed': not wrong,
            'score': {'correct': len(answers) - len(wrong), 'total': len(questions)},
            'answers': [{
                'question_id': answer.question_id.id, 'answer_id': answer.id,
                'is_correct': answer.is_correct, 'comment': answer.comment or None,
            } for answer in answers],
            'completed': slide.user_has_completed,
            'attempts': _reading(slide).quiz_attempts_count,
            'course_completion': slide.channel_id.completion,
        })
