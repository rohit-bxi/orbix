# -*- coding: utf-8 -*-

import json

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth


class BxiLibraryBookRequestController(http.Controller):

    @http.route('/api/v1/library/book-requests', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_requests(self, **kwargs):
        user = request.env.user
        domain = [] if user.has_group('bxi_library_book_request.group_book_request_librarian') \
            else [('requester_user_id', '=', user.id)]
        requests = request.env['bxi.library.book.request'].sudo().search(domain, order='create_date desc')
        return api_response({
            'requests': [{
                'id': r.id, 'name': r.name, 'media': r.media_id.display_name,
                'status': r.status, 'reason': r.reason, 'review_notes': r.review_notes,
                'create_date': r.create_date.isoformat(),
            } for r in requests],
        })

    @http.route('/api/v1/library/book-requests', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_request(self, **kwargs):
        payload = request.get_json_data()
        media_id = payload.get('media_id')
        if not media_id:
            return api_error('media_id is required.', status=400, code='missing_media_id')

        media_id, error = parse_int(media_id, 'media_id')
        if error:
            return error
        media = request.env['op.media'].sudo().browse(media_id)
        if not media.exists():
            return api_error('Book/resource not found.', status=404, code='not_found')

        teacher = request.env['op.faculty'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)
        book_request = request.env['bxi.library.book.request'].sudo().create({
            'requester_user_id': request.env.user.id,
            'teacher_id': teacher.id if teacher else False,
            'media_id': media.id,
            'reason': payload.get('reason'),
        })
        return api_response({'id': book_request.id, 'name': book_request.name, 'status': book_request.status})

    @http.route('/api/v1/library/book-requests/<int:request_id>/approve', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def approve_request(self, request_id, **kwargs):
        return self._review(request_id, 'approve')

    @http.route('/api/v1/library/book-requests/<int:request_id>/reject', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reject_request(self, request_id, **kwargs):
        return self._review(request_id, 'reject')

    def _review(self, request_id, action):
        user = request.env.user
        if not user.has_group('bxi_library_book_request.group_book_request_librarian'):
            return api_error('Not authorized to review book requests.', status=403, code='forbidden')

        book_request = request.env['bxi.library.book.request'].sudo().browse(int(request_id))
        if not book_request.exists():
            return api_error('Request not found.', status=404, code='not_found')

        raw_body = request.httprequest.get_data(as_text=True)
        payload = json.loads(raw_body) if raw_body else {}
        notes = payload.get('notes')
        try:
            if action == 'approve':
                book_request.action_approve(notes=notes)
            else:
                book_request.action_reject(notes=notes)
        except UserError as exc:
            return api_error(str(exc), status=400, code='invalid_transition')
        return api_response({'id': book_request.id, 'status': book_request.status})
