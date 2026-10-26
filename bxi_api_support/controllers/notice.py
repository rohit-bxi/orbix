# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth

from .common import audience_domain, parse_pagination, safe_create

MANAGER_GROUP = 'bxi_school_notice.group_notice_manager'

# Mirrors bxi.notice's _resolve_recipient_partners; 'specific_class' is
# matched per class in audience_domain (parents see their children's).
AUDIENCES_BY_ROLE = {
    'student': ('all_students', 'all_classes', 'students_and_families'),
    'parent': ('all_parents', 'students_and_families'),
    'teacher': ('all_teachers',),
    'staff': ('all_teachers',),
}

CREATE_FIELDS = ('title', 'body', 'category', 'target_audience', 'expires_on', 'is_pinned')


def _is_notice_manager(user):
    return user.has_group(MANAGER_GROUP)


def _visible_domain(env):
    if _is_notice_manager(env.user):
        return Domain.TRUE
    return Domain.AND([
        Domain('active', '=', True),
        Domain('is_expired', '=', False),
        audience_domain(env, AUDIENCES_BY_ROLE),
    ])


def _notice_dict(notice):
    return {
        'id': notice.id,
        'name': notice.name,
        'title': notice.title,
        'body': notice.body,
        'category': notice.category,
        'target_audience': notice.target_audience,
        'expires_on': notice.expires_on and notice.expires_on.isoformat(),
        'is_expired': notice.is_expired,
        'is_pinned': notice.is_pinned,
        'posted_date': notice.posted_date and notice.posted_date.isoformat(),
    }


class BxiApiSupportNoticeController(http.Controller):

    @http.route('/api/v1/notices', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_notices(self, **kwargs):
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = _visible_domain(request.env)
        Notice = request.env['bxi.notice'].sudo()
        total = Notice.search_count(domain)
        notices = Notice.search(domain, limit=limit, offset=offset)
        return api_response(
            {'notices': [_notice_dict(n) for n in notices]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/notices/<int:notice_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_notice(self, notice_id, **kwargs):
        notice = request.env['bxi.notice'].sudo().browse(notice_id)
        if not notice.exists():
            return api_error('Notice not found.', status=404, code='not_found')
        if not notice.filtered_domain(_visible_domain(request.env)):
            return api_error('Not authorized for this notice.', status=403, code='forbidden')
        return api_response(_notice_dict(notice))

    @http.route('/api/v1/notices', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_notice(self, **kwargs):
        if not _is_notice_manager(request.env.user):
            return api_error('Not authorized to post notices.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        if not payload.get('title'):
            return api_error('title is required.', status=400, code='missing_title')
        if not payload.get('body'):
            return api_error('body is required.', status=400, code='missing_body')
        vals = {key: payload[key] for key in CREATE_FIELDS if key in payload}
        if payload.get('course_ids'):
            vals['course_ids'] = [(6, 0, payload['course_ids'])]
        if payload.get('batch_ids'):
            vals['batch_ids'] = [(6, 0, payload['batch_ids'])]
        notice, error = safe_create(request.env['bxi.notice'].sudo(), vals)
        if error:
            return error
        return api_response(_notice_dict(notice), status=201)

    @http.route('/api/v1/notices/<int:notice_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_notice(self, notice_id, **kwargs):
        if not _is_notice_manager(request.env.user):
            return api_error('Not authorized to edit notices.', status=403, code='forbidden')
        notice = request.env['bxi.notice'].sudo().browse(notice_id)
        if not notice.exists():
            return api_error('Notice not found.', status=404, code='not_found')
        payload = request.get_json_data() or {}
        vals = {key: payload[key] for key in CREATE_FIELDS if key in payload}
        if payload.get('course_ids'):
            vals['course_ids'] = [(6, 0, payload['course_ids'])]
        if payload.get('batch_ids'):
            vals['batch_ids'] = [(6, 0, payload['batch_ids'])]
        notice.write(vals)
        return api_response(_notice_dict(notice))

    @http.route('/api/v1/notices/<int:notice_id>/toggle-pin', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def toggle_pin_notice(self, notice_id, **kwargs):
        if not _is_notice_manager(request.env.user):
            return api_error('Not authorized to manage notices.', status=403, code='forbidden')
        notice = request.env['bxi.notice'].sudo().browse(notice_id)
        if not notice.exists():
            return api_error('Notice not found.', status=404, code='not_found')
        notice.action_toggle_pin()
        return api_response(_notice_dict(notice))
