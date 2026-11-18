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

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain
from odoo.http import request
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
        data.update({
            'description': slide.description or None,
            'url': slide.url or None,
            'html_content': slide.html_content or None if slide.slide_category == 'article' else None,
            'has_file': bool(slide.binary_content) or (slide.slide_category == 'infographic' and bool(slide.image_1920)),
            'website_url': slide.website_url or None,
        })
    return data


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
    def courses(self, class_id=None, section_id=None, q=None, joined=None, **kwargs):
        """?class_id= / ?section_id= (eLearning ids), ?q= (name), ?joined=1
        (only courses the user has joined)."""
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
        Channel = _visible_courses()
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
    def lesson(self, slide_id, **kwargs):
        """A lesson's content. Opening it as a member records it as viewed."""
        slide, error = self._lesson(slide_id)
        if error:
            return error
        if slide.channel_id.is_member:
            slide._action_set_viewed(request.env.user.partner_id)
        return api_response(dict(_lesson_dict(slide, content=True), course=_ref(slide.channel_id)))

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
