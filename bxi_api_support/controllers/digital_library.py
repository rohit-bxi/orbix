# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The student app's Digital Library: reading stats and streak, books per
category, Continue Reading, Trending This Week and recommendations, plus
reading progress and the reading list (bxi_student_learning). A book is
"digital" when its catalogue entry carries a file. Recommendations are
rules over the school's own data - nothing goes to an outside service."""
from collections import Counter
from datetime import timedelta

from odoo import fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_file_response, api_response, parse_int, require_auth

from .common import date_str, get_app_student, json_body, ref, running_enrollment
from .library import _media_dict

TRENDING_DAYS = 7
TOP = 6


def _book_dict(media, progress=None, listed=None):
    data = dict(_media_dict(media), subjects=[ref(s) for s in media.subject_ids],
                classes=[ref(c) for c in media.course_ids], has_file=bool(media.attachment_ids))
    if progress is not None:
        data['progress'] = {
            'percent': round(progress.percent, 1), 'current_page': progress.current_page or None,
            'total_pages': progress.total_pages or None, 'chapter': progress.chapter or None,
            'last_read': date_str(progress.last_read), 'completed': progress.completed,
        } if progress else None
    if listed is not None:
        data['in_reading_list'] = listed
    return data


class BxiApiSupportDigitalLibraryController(http.Controller):

    def _student(self, student_id=None):
        return get_app_student(request.env, student_id)

    @http.route('/api/v1/library/digital', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def digital(self, student_id=None, **kwargs):
        """The Digital Library home: `stats` (total books, completed,
        reading now, day streak), `categories` (books per genre),
        `continue_reading`, `trending` (most issued and read in the last 7
        days) and `recommendations` (books for the student's class subjects
        or the genres they read, not yet started)."""
        env = request.env
        student, error = self._student(student_id)
        if error:
            return error
        Media = env['op.media'].sudo()
        progress = env['bxi.reading.progress'].sudo().search([('student_id', '=', student.id)])
        listed = env['bxi.reading.list.item'].sudo().search([('student_id', '=', student.id)]).media_id
        today = fields.Date.context_today(Media)

        # Counted record by record: mapped() would de-duplicate.
        genres = Counter(media.genre_id for media in Media.search([]))
        since = fields.Datetime.now() - timedelta(days=TRENDING_DAYS)
        popularity = Counter(move.media_id for move in env['op.media.movement'].sudo().search(
            [('issued_date', '>=', since.date())]))
        popularity.update(p.media_id for p in env['bxi.reading.progress'].sudo().search([('last_read', '>=', since)]))
        trending = [media for media, _count in popularity.most_common(TOP)]

        enrollment = running_enrollment(student)
        class_subjects = enrollment.course_id.subject_ids if enrollment else env['op.subject']
        read_genres = progress.media_id.genre_id
        started = progress.media_id
        candidates = Media.search(['|', ('subject_ids', 'in', class_subjects.ids), ('genre_id', 'in', read_genres.ids),
                                   ('id', 'not in', started.ids)], limit=TOP * 3)
        recommendations = []
        for media in candidates:
            subject = (media.subject_ids & class_subjects)[:1]
            reason = ('For your %s class' % subject.name) if subject else (
                'Because you read %s books' % media.genre_id.name if media.genre_id else 'Recommended for you')
            recommendations.append(dict(_book_dict(media, listed=media in listed), reason=reason))
            if len(recommendations) >= 3:
                break

        reading_now = progress.filtered(lambda p: not p.completed).sorted('last_read', reverse=True)
        return api_response({
            'stats': {
                'total_books': Media.search_count([]),
                'completed': len(progress.filtered('completed')),
                'reading_now': len(reading_now),
                'day_streak': env['bxi.reading.day'].sudo()._bxi_streak(student, today),
            },
            'categories': [{'id': genre.id, 'name': genre.name, 'count': count}
                           for genre, count in sorted(genres.items(), key=lambda kv: kv[0].name or '') if genre],
            'continue_reading': [_book_dict(p.media_id, progress=p, listed=p.media_id in listed)
                                 for p in reading_now[:5]],
            'trending': [_book_dict(media, listed=media in listed) for media in trending],
            'recommendations': recommendations,
        })

    @http.route('/api/v1/library/catalog/<int:media_id>/progress', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def save_progress(self, media_id, **kwargs):
        """The student's own place in a book: {"percent"} or {"current_page",
        "total_pages"}, plus "chapter"? Counts today towards the streak."""
        env = request.env
        student, error = self._student(kwargs.get('student_id'))
        if error:
            return error
        media = env['op.media'].sudo().browse(media_id).exists()
        if not media:
            return api_error('Book not found.', status=404, code='not_found')
        payload = json_body() or {}
        vals = {'last_read': fields.Datetime.now()}
        for key in ('current_page', 'total_pages'):
            if key in payload:
                value, error = parse_int(payload[key], key)
                if error:
                    return error
                if value < 0:
                    return api_error('%s cannot be negative.' % key, status=400, code='invalid_%s' % key)
                vals[key] = value
        if 'percent' in payload:
            try:
                vals['percent'] = float(payload['percent'])
            except (TypeError, ValueError):
                return api_error('percent must be a number.', status=400, code='invalid_percent')
        elif vals.get('total_pages'):
            vals['percent'] = 100.0 * vals.get('current_page', 0) / vals['total_pages']
        if 'percent' not in vals:
            return api_error('Send percent, or current_page and total_pages.', status=400, code='missing_progress')
        if not 0 <= vals['percent'] <= 100 or vals.get('current_page', 0) > (vals.get('total_pages') or
                                                                             vals.get('current_page', 0)):
            return api_error('The position is outside the book.', status=400, code='invalid_progress')
        if 'chapter' in payload:
            vals['chapter'] = str(payload['chapter'] or '')[:200] or False
        Progress = env['bxi.reading.progress'].sudo()
        progress = Progress.search([('student_id', '=', student.id), ('media_id', '=', media.id)], limit=1)
        if progress:
            progress.write(vals)
        else:
            progress = Progress.create(dict(vals, student_id=student.id, media_id=media.id))
        env['bxi.reading.day']._bxi_mark(student, fields.Date.context_today(progress))
        return api_response(_book_dict(media, progress=progress))

    @http.route('/api/v1/library/reading-list', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def reading_list(self, student_id=None, **kwargs):
        student, error = self._student(student_id)
        if error:
            return error
        env = request.env
        items = env['bxi.reading.list.item'].sudo().search([('student_id', '=', student.id)])
        progress = {p.media_id.id: p for p in env['bxi.reading.progress'].sudo().search(
            [('student_id', '=', student.id), ('media_id', 'in', items.media_id.ids)])}
        return api_response({'books': [
            _book_dict(item.media_id, progress=progress.get(item.media_id.id, env['bxi.reading.progress']),
                       listed=True) for item in items]})

    @http.route('/api/v1/library/reading-list/<int:media_id>', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def toggle_reading_list(self, media_id, **kwargs):
        """{"add": true|false}; without it, toggles."""
        student, error = self._student(kwargs.get('student_id'))
        if error:
            return error
        env = request.env
        media = env['op.media'].sudo().browse(media_id).exists()
        if not media:
            return api_error('Book not found.', status=404, code='not_found')
        Item = env['bxi.reading.list.item'].sudo()
        item = Item.search([('student_id', '=', student.id), ('media_id', '=', media.id)], limit=1)
        payload = json_body() or {}
        add = payload['add'] if 'add' in payload else not item
        if add and not item:
            Item.create({'student_id': student.id, 'media_id': media.id})
        elif not add and item:
            item.unlink()
        return api_response({'id': media.id, 'in_reading_list': bool(add)})

    @http.route('/api/v1/library/catalog/<int:media_id>/file', type='http', auth='public', methods=['GET'],
                csrf=False)
    @require_auth
    def book_file(self, media_id, **kwargs):
        """The digital book itself (its first file, a PDF when there is one)."""
        media = request.env['op.media'].sudo().browse(media_id).exists()
        if not media:
            return api_error('Book not found.', status=404, code='not_found')
        files = media.attachment_ids
        attachment = files.filtered(lambda a: a.mimetype == 'application/pdf')[:1] or files[:1]
        if not attachment:
            return api_error('This book has no digital copy.', status=404, code='no_file')
        return api_file_response(attachment.raw, attachment.name, attachment.mimetype or 'application/octet-stream')
