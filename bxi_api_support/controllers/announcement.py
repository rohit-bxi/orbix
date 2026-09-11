# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import parse_pagination, safe_create

MANAGER_GROUP = 'bxi_school_announcement.group_announcement_manager'

CREATE_FIELDS = (
    'title', 'category', 'body', 'priority', 'target_audience', 'course_ids', 'batch_ids',
    'schedule_date', 'channel_in_app', 'channel_email', 'channel_sms', 'channel_push',
)


def _is_announcement_manager(user):
    return user.has_group(MANAGER_GROUP)


def _announcement_dict(announcement):
    return {
        'id': announcement.id,
        'name': announcement.name,
        'title': announcement.title,
        'category': announcement.category,
        'body': announcement.body,
        'priority': announcement.priority,
        'target_audience': announcement.target_audience,
        'state': announcement.state,
        'schedule_date': announcement.schedule_date and announcement.schedule_date.isoformat(),
        'published_date': announcement.published_date and announcement.published_date.isoformat(),
        'recipient_count': announcement.recipient_count,
    }


class BxiApiSupportAnnouncementController(http.Controller):

    @http.route('/api/v1/announcements', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_announcements(self, **kwargs):
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [] if _is_announcement_manager(request.env.user) else [('state', '=', 'published')]
        Announcement = request.env['bxi.announcement'].sudo()
        total = Announcement.search_count(domain)
        announcements = Announcement.search(domain, limit=limit, offset=offset, order='create_date desc')
        return api_response(
            {'announcements': [_announcement_dict(a) for a in announcements]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/announcements/<int:announcement_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_announcement(self, announcement_id, **kwargs):
        announcement = request.env['bxi.announcement'].sudo().browse(announcement_id)
        if not announcement.exists():
            return api_error('Announcement not found.', status=404, code='not_found')
        if announcement.state != 'published' and not _is_announcement_manager(request.env.user):
            return api_error('Not authorized for this announcement.', status=403, code='forbidden')
        return api_response(_announcement_dict(announcement))

    @http.route('/api/v1/announcements', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_announcement(self, **kwargs):
        if not _is_announcement_manager(request.env.user):
            return api_error('Not authorized to create announcements.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        if not payload.get('title'):
            return api_error('title is required.', status=400, code='missing_title')
        if not payload.get('body'):
            return api_error('body is required.', status=400, code='missing_body')

        vals = {key: payload[key] for key in CREATE_FIELDS if key in payload and key not in ('course_ids', 'batch_ids')}
        if payload.get('course_ids'):
            vals['course_ids'] = [(6, 0, payload['course_ids'])]
        if payload.get('batch_ids'):
            vals['batch_ids'] = [(6, 0, payload['batch_ids'])]
        announcement, error = safe_create(request.env['bxi.announcement'].sudo(), vals)
        if error:
            return error
        return api_response(_announcement_dict(announcement), status=201)

    @http.route('/api/v1/announcements/<int:announcement_id>/publish', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def publish_announcement(self, announcement_id, **kwargs):
        return self._transition(announcement_id, 'action_publish')

    @http.route('/api/v1/announcements/<int:announcement_id>/reset-to-draft', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reset_announcement(self, announcement_id, **kwargs):
        return self._transition(announcement_id, 'action_reset_to_draft')

    @http.route('/api/v1/announcements/<int:announcement_id>/archive', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def archive_announcement(self, announcement_id, **kwargs):
        return self._transition(announcement_id, 'action_archive_announcement')

    def _transition(self, announcement_id, method_name):
        if not _is_announcement_manager(request.env.user):
            return api_error('Not authorized to manage announcements.', status=403, code='forbidden')
        announcement = request.env['bxi.announcement'].sudo().browse(announcement_id)
        if not announcement.exists():
            return api_error('Announcement not found.', status=404, code='not_found')
        _, error = call_action(announcement, method_name)
        if error:
            return error
        return api_response(_announcement_dict(announcement))
