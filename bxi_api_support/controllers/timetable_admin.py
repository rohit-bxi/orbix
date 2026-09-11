# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import parse_pagination, safe_create

COORDINATOR_GROUP = 'bxi_class_timetable_inhencement.group_class_timetable_coordinator'
MANAGER_GROUP = 'bxi_class_timetable_inhencement.group_class_timetable_manager'


def _is_timetable_staff(user):
    return user.has_group(COORDINATOR_GROUP) or user.has_group(MANAGER_GROUP)


def _timetable_dict(timetable):
    return {
        'id': timetable.id,
        'display_name': timetable.display_name,
        'course': timetable.course_id.display_name,
        'batch': timetable.batch_id.display_name,
        'locked': timetable.locked,
        'lines': [{
            'id': line.id, 'day': line.day, 'timing': line.timing_id.display_label,
            'subject': line.subject_id.display_name, 'teacher': line.teacher_id.display_name,
        } for line in timetable.line_ids],
    }


def _workload_dict(faculty):
    return {
        'id': faculty.id,
        'name': faculty.name,
        'max_weekly_periods': faculty.max_weekly_periods,
        'weekly_period_count': faculty.weekly_period_count,
        'workload_status': faculty.workload_status,
    }


class BxiApiSupportTimetableAdminController(http.Controller):

    @http.route('/api/v1/timetable/admin/timetables', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_timetables(self, course_id=None, batch_id=None, **kwargs):
        if not _is_timetable_staff(request.env.user):
            return api_error('Not authorized to view timetables.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = []
        if course_id:
            domain.append(('course_id', '=', int(course_id)))
        if batch_id:
            domain.append(('batch_id', '=', int(batch_id)))
        Timetable = request.env['bxi.timetable'].sudo()
        total = Timetable.search_count(domain)
        timetables = Timetable.search(domain, limit=limit, offset=offset)
        return api_response(
            {'timetables': [_timetable_dict(t) for t in timetables]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/timetable/admin/timetables/<int:timetable_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_timetable(self, timetable_id, **kwargs):
        if not _is_timetable_staff(request.env.user):
            return api_error('Not authorized to view timetables.', status=403, code='forbidden')
        timetable = request.env['bxi.timetable'].sudo().browse(timetable_id)
        if not timetable.exists():
            return api_error('Timetable not found.', status=404, code='not_found')
        return api_response(_timetable_dict(timetable))

    @http.route('/api/v1/timetable/admin/timetables/<int:timetable_id>/lock', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def lock_timetable(self, timetable_id, **kwargs):
        return self._transition(timetable_id, 'action_lock')

    @http.route('/api/v1/timetable/admin/timetables/<int:timetable_id>/unlock', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def unlock_timetable(self, timetable_id, **kwargs):
        return self._transition(timetable_id, 'action_unlock')

    def _transition(self, timetable_id, method_name):
        if not _is_timetable_staff(request.env.user):
            return api_error('Not authorized to manage timetables.', status=403, code='forbidden')
        timetable = request.env['bxi.timetable'].sudo().browse(timetable_id)
        if not timetable.exists():
            return api_error('Timetable not found.', status=404, code='not_found')
        _, error = call_action(timetable, method_name)
        if error:
            return error
        return api_response(_timetable_dict(timetable))

    @http.route('/api/v1/timetable/admin/add-period', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def add_period(self, **kwargs):
        return self._run_wizard('bxi.add.period.wizard', 'action_add_period', (
            'teacher_id', 'course_id', 'batch_id', 'day', 'timing_id', 'subject_id',
        ))

    @http.route('/api/v1/timetable/admin/remove-period', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def remove_period(self, **kwargs):
        return self._run_wizard('bxi.remove.period.wizard', 'action_remove_period', ('line_id',))

    @http.route('/api/v1/timetable/admin/reassign-class', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reassign_class(self, **kwargs):
        return self._run_wizard('bxi.reassign.class.wizard', 'action_reassign', (
            'teacher_id', 'current_course_id', 'current_batch_id', 'new_course_id', 'new_batch_id',
        ))

    @http.route('/api/v1/timetable/admin/transfer-period', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def transfer_period(self, **kwargs):
        return self._run_wizard('bxi.transfer.period.wizard', 'action_transfer', (
            'from_teacher_id', 'course_id', 'batch_id', 'day', 'timing_id', 'to_teacher_id',
        ))

    def _run_wizard(self, model_name, method_name, required_fields):
        if not _is_timetable_staff(request.env.user):
            return api_error('Not authorized to manage timetables.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        missing = [f for f in required_fields if not payload.get(f)]
        if missing:
            return api_error('Missing required field(s): %s' % ', '.join(missing), status=400, code='missing_fields')

        vals = {key: payload[key] for key in required_fields}
        context = {'force_workload_override': True} if payload.get('force_workload_override') else {}
        wizard, error = safe_create(request.env[model_name].sudo().with_context(**context), vals)
        if error:
            return error
        _, error = call_action(wizard, method_name)
        if error:
            return error
        return api_response({'success': True})

    @http.route('/api/v1/timetable/admin/faculty-workload', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def faculty_workload(self, **kwargs):
        if not _is_timetable_staff(request.env.user):
            return api_error('Not authorized to view faculty workload.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Faculty = request.env['op.faculty'].sudo()
        total = Faculty.search_count([])
        faculties = Faculty.search([], limit=limit, offset=offset)
        return api_response(
            {'faculty': [_workload_dict(f) for f in faculties]},
            meta={'total': total, 'limit': limit, 'offset': offset})
