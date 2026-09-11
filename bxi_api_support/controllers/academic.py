# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import parse_pagination

COORDINATOR_GROUP = 'bxi_academic_management.group_academic_coordinator'
MANAGER_GROUP = 'bxi_academic_management.group_academic_manager'


def _is_coordinator_or_manager(user):
    return user.has_group(COORDINATOR_GROUP) or user.has_group(MANAGER_GROUP)


def _curriculum_dict(curriculum):
    return {
        'id': curriculum.id,
        'name': curriculum.name,
        'board': curriculum.board_id.display_name,
        'description': curriculum.description,
        'classes': curriculum.class_ids.mapped('display_name'),
        'approval_status': curriculum.approval_status,
        'locked': curriculum.locked,
    }


def _mapping_dict(mapping):
    return {
        'id': mapping.id,
        'subject': mapping.subject_id.display_name,
        'class': mapping.class_id.display_name,
        'teacher': mapping.teacher_id.display_name,
        'curriculum': mapping.curriculum_id.display_name,
    }


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
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Curriculum = request.env['bxi.curriculum'].sudo()
        total = Curriculum.search_count([])
        curricula = Curriculum.search([], limit=limit, offset=offset, order='id desc')
        return api_response(
            {'curricula': [_curriculum_dict(c) for c in curricula]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/academic/curricula/<int:curriculum_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_curriculum(self, curriculum_id, **kwargs):
        curriculum = request.env['bxi.curriculum'].sudo().browse(curriculum_id)
        if not curriculum.exists():
            return api_error('Curriculum not found.', status=404, code='not_found')
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

    @http.route('/api/v1/academic/subject-mappings', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_subject_mappings(self, class_id=None, teacher_id=None, **kwargs):
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = []
        if class_id:
            domain.append(('class_id', '=', int(class_id)))
        if teacher_id:
            domain.append(('teacher_id', '=', int(teacher_id)))
        Mapping = request.env['bxi.subject.mapping'].sudo()
        total = Mapping.search_count(domain)
        mappings = Mapping.search(domain, limit=limit, offset=offset, order='id desc')
        return api_response(
            {'mappings': [_mapping_dict(m) for m in mappings]},
            meta={'total': total, 'limit': limit, 'offset': offset})

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
