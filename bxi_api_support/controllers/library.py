# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Library circulation (openeducat_library): catalogue search, a student's
loans/history/reservations, and the librarian's issue/return desk. Teacher
book requests stay on bxi_library_book_request's /library/book-requests."""
from datetime import timedelta

from odoo import fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, parse_int, require_auth

from .common import date_str, get_viewable_student, parse_pagination, ref, safe_create, school_context

LIBRARY_STAFF_GROUPS = ('openeducat_library.group_op_library', 'openeducat_library.group_op_library_user')
ACTIVE_LOAN_STATES = ('issue', 'reserve')
CLOSED_LOAN_STATES = ('return', 'return_done', 'lost')


def _is_library_staff(user):
    return any(user.has_group(group) for group in LIBRARY_STAFF_GROUPS)


def _media_dict(media, detail=False):
    data = {
        'id': media.id,
        'title': media.name,
        'isbn': media.isbn or None,
        'authors': [a.name for a in media.author_ids],
        'publishers': [p.name for p in media.publisher_ids],
        'edition': media.edition or None,
        'genre': ref(media.genre_id),
        'media_type': ref(media.media_type_id),
        'language': media.language or None,
        'publish_year': media.publish_year or None,
        'shelf_location': media.shelf_location or None,
        'available_copies': media.available_copies,
        'total_copies': media.total_copies or len(media.unit_ids),
        'status': media.status,
    }
    if detail:
        data.update({
            'description': media.description or None,
            'subjects': [ref(s) for s in media.subject_ids],
            'classes': [ref(c) for c in media.course_ids],
            'pages': media.number_of_pages or None,
            'tags': [t.name for t in media.tags],
        })
    return data


def _loan_dict(movement):
    today = fields.Date.context_today(movement)
    overdue_days = (today - movement.return_date).days if movement.return_date and movement.state == 'issue' else 0
    per_day = movement.library_card_id.library_card_type_id.penalty_amt_per_day
    return {
        'id': movement.id,
        'media': {'id': movement.media_id.id, 'title': movement.media_id.name},
        'copy': {'id': movement.media_unit_id.id, 'name': movement.media_unit_id.name,
                 'barcode': movement.media_unit_id.barcode or None},
        'issued_date': date_str(movement.issued_date),
        'due_date': date_str(movement.return_date),
        'returned_date': date_str(movement.actual_return_date),
        'state': movement.state,
        'is_overdue': overdue_days > 0,
        'overdue_days': max(overdue_days, 0),
        # Running fine while still out; the booked penalty once returned.
        'fine': movement.penalty if movement.state != 'issue' else max(overdue_days, 0) * per_day,
    }


def _reservation_dict(queue):
    return {
        'id': queue.id,
        'name': queue.name,
        'media': {'id': queue.media_id.id, 'title': queue.media_id.name},
        'date_from': date_str(queue.date_from),
        'date_to': date_str(queue.date_to),
        'state': queue.state,
    }


class BxiApiSupportLibraryController(http.Controller):

    @http.route('/api/v1/library/catalog', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def catalog(self, q=None, genre_id=None, course_id=None, available=None, **kwargs):
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = []
        if q:
            domain += ['|', '|', '|', ('name', 'ilike', q), ('isbn', 'ilike', q),
                       ('author_ids.name', 'ilike', q), ('internal_code', 'ilike', q)]
        for param, raw, field in (('genre_id', genre_id, 'genre_id'), ('course_id', course_id, 'course_ids')):
            if raw:
                value, error = parse_int(raw, param)
                if error:
                    return error
                domain.append((field, 'in' if field.endswith('_ids') else '=', value))
        if available in ('1', 'true', 'True'):
            domain.append(('available_copies', '>', 0))
        Media = request.env['op.media'].sudo()
        total = Media.search_count(domain)
        media = Media.search(domain, limit=limit, offset=offset, order='name')
        return api_response({'items': [_media_dict(m) for m in media]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/library/catalog/<int:media_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def catalog_item(self, media_id, **kwargs):
        media = request.env['op.media'].sudo().browse(media_id)
        if not media.exists():
            return api_error('Book not found.', status=404, code='not_found')
        return api_response(_media_dict(media, detail=True))

    @http.route('/api/v1/library/my-loans', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def my_loans(self, student_id=None, **kwargs):
        return self._loans(student_id, ACTIVE_LOAN_STATES, kwargs)

    @http.route('/api/v1/library/history', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def history(self, student_id=None, **kwargs):
        return self._loans(student_id, CLOSED_LOAN_STATES, kwargs)

    def _loans(self, student_id, states, kwargs):
        """A student's loans (family/teachers via student_id) or, with no
        student_id, the calling teacher's own."""
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        if student_id:
            student, error = get_viewable_student(request.env, student_id)
            if error:
                return error
            domain = [('student_id', '=', student.id)]
        else:
            faculty = school_context(request.env)['faculty']
            if not faculty:
                return api_error('student_id is required.', status=400, code='missing_student_id')
            domain = [('faculty_id', '=', faculty.id)]
        domain.append(('state', 'in', states))
        Movement = request.env['op.media.movement'].sudo()
        total = Movement.search_count(domain)
        loans = Movement.search(domain, limit=limit, offset=offset, order='issued_date desc, id desc')
        return api_response({'loans': [_loan_dict(m) for m in loans]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/library/reservations', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_reservations(self, **kwargs):
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Queue = request.env['op.media.queue'].sudo()
        domain = [] if _is_library_staff(request.env.user) else [('user_id', '=', request.env.user.id)]
        if kwargs.get('state'):
            domain.append(('state', '=', kwargs['state']))
        total = Queue.search_count(domain)
        queues = Queue.search(domain, limit=limit, offset=offset, order='id desc')
        return api_response({'reservations': [_reservation_dict(q) for q in queues]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/library/reservations', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_reservation(self, **kwargs):
        """A student or teacher queues for a book. openeducat refuses
        reservations from parent logins, so parents get a clean 403."""
        context = school_context(request.env)
        patron = context['student'] or context['faculty']
        if not patron:
            return api_error('Only students and teachers can reserve books.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        media_id, error = parse_int(payload.get('media_id'), 'media_id')
        if error:
            return error
        media = request.env['op.media'].sudo().browse(media_id)
        if not media.exists():
            return api_error('Book not found.', status=404, code='not_found')
        if request.env['op.media.queue'].sudo().search_count([
            ('media_id', '=', media.id), ('user_id', '=', request.env.user.id), ('state', '=', 'request'),
        ]):
            return api_error('You already have a pending reservation for this book.', status=400, code='duplicate')
        today = fields.Date.context_today(media)
        queue, error = safe_create(request.env['op.media.queue'].sudo(), {
            'media_id': media.id,
            'partner_id': patron.partner_id.id,
            'user_id': request.env.user.id,
            'date_from': payload.get('date_from') or today,
            'date_to': payload.get('date_to') or today + timedelta(days=7),
        })
        if error:
            return error
        return api_response(_reservation_dict(queue), status=201)

    @http.route('/api/v1/library/reservations/<int:queue_id>/<any("accept", "reject"):action>',
                type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def review_reservation(self, queue_id, action, **kwargs):
        if not _is_library_staff(request.env.user):
            return api_error('Only library staff can review reservations.', status=403, code='forbidden')
        queue = request.env['op.media.queue'].sudo().browse(queue_id)
        if not queue.exists():
            return api_error('Reservation not found.', status=404, code='not_found')
        if queue.state != 'request':
            return api_error('This reservation was already reviewed.', status=400, code='invalid_transition')
        _, error = call_action(queue, 'do_accept' if action == 'accept' else 'do_reject')
        if error:
            return error
        return api_response(_reservation_dict(queue))

    @http.route('/api/v1/library/issue', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def issue(self, **kwargs):
        """Librarian desk: {"barcode" or "media_unit_id", "student_id" or
        "faculty_id", "return_date"?}. Runs openeducat's own issue wizard,
        so the card's borrowing limit still applies."""
        if not _is_library_staff(request.env.user):
            return api_error('Only library staff can issue books.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        Unit = request.env['op.media.unit'].sudo()
        if payload.get('barcode'):
            unit = Unit.search([('barcode', '=', payload['barcode'])], limit=1)
        else:
            unit_id, error = parse_int(payload.get('media_unit_id'), 'media_unit_id')
            if error:
                return error
            unit = Unit.browse(unit_id).exists()
        if not unit:
            return api_error('Book copy not found.', status=404, code='not_found')
        patron_type = 'student' if payload.get('student_id') else 'faculty' if payload.get('faculty_id') else None
        if not patron_type:
            return api_error('student_id or faculty_id is required.', status=400, code='missing_patron')
        patron_field = f'{patron_type}_id'
        patron_id, error = parse_int(payload[patron_field], patron_field)
        if error:
            return error
        card = request.env['op.library.card'].sudo().search([(patron_field, '=', patron_id)], limit=1)
        if not card:
            return api_error('This borrower has no library card.', status=400, code='no_library_card')
        today = fields.Date.context_today(unit)
        wizard, error = safe_create(request.env['issue.media'].sudo(), {
            'media_id': unit.media_id.id,
            'media_unit_id': unit.id,
            'type': patron_type,
            'student_id': card.student_id.id,
            'faculty_id': card.faculty_id.id,
            'library_card_id': card.id,
            'issued_date': today,
            'return_date': payload.get('return_date') or today + timedelta(
                days=card.library_card_type_id.duration or 14),
        })
        if error:
            return error
        _, error = call_action(wizard, 'do_issue')
        if error:
            return error
        movement = request.env['op.media.movement'].sudo().search(
            [('media_unit_id', '=', unit.id), ('state', '=', 'issue')], order='id desc', limit=1)
        return api_response(_loan_dict(movement), status=201)

    @http.route('/api/v1/library/loans/<int:movement_id>/return', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def return_loan(self, movement_id, **kwargs):
        if not _is_library_staff(request.env.user):
            return api_error('Only library staff can take returns.', status=403, code='forbidden')
        movement = request.env['op.media.movement'].sudo().browse(movement_id)
        if not movement.exists():
            return api_error('Loan not found.', status=404, code='not_found')
        if movement.state != 'issue':
            return api_error('This book is not currently issued.', status=400, code='invalid_transition')
        payload = request.get_json_data() if request.httprequest.get_data() else {}
        return_date = (payload or {}).get('return_date') or fields.Date.context_today(movement)
        _, error = call_action(movement, 'return_media', return_date=fields.Date.to_date(return_date))
        if error:
            return error
        return api_response(_loan_dict(movement))
