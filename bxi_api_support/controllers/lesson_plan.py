# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import get_own_faculty, parse_pagination, safe_create

COORDINATOR_GROUP = 'bxi_academic_management.group_academic_coordinator'
MANAGER_GROUP = 'bxi_academic_management.group_academic_manager'

CREATE_FIELDS = (
    'subject_id', 'class_id', 'quarter_id', 'topic', 'objective', 'activities',
    'resources', 'assessment_method', 'start_date', 'end_date', 'plan_date',
)


def _is_coordinator_or_manager(user):
    return user.has_group(COORDINATOR_GROUP) or user.has_group(MANAGER_GROUP)


def _plan_dict(plan):
    return {
        'id': plan.id,
        'teacher': plan.teacher_id.display_name,
        'subject': plan.subject_id.display_name,
        'class': plan.class_id.display_name,
        'quarter': plan.quarter_id.display_name,
        'topic': plan.topic,
        'objective': plan.objective,
        'start_date': plan.start_date and plan.start_date.isoformat(),
        'end_date': plan.end_date and plan.end_date.isoformat(),
        'plan_date': plan.plan_date and plan.plan_date.isoformat(),
        'state': plan.state,
        'lines': [{
            'id': line.id, 'line_type': line.line_type, 'name': line.name,
        } for line in plan.line_ids],
    }


class BxiApiSupportLessonPlanController(http.Controller):

    @http.route('/api/v1/lesson-plans', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_plans(self, **kwargs):
        user = request.env.user
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        if _is_coordinator_or_manager(user):
            domain = []
        else:
            faculty = get_own_faculty(request.env)
            domain = [('teacher_id', '=', faculty.id)] if faculty else [('id', '=', 0)]
        Plan = request.env['bxi.lesson.plan'].sudo()
        total = Plan.search_count(domain)
        plans = Plan.search(domain, limit=limit, offset=offset, order='id desc')
        return api_response(
            {'plans': [_plan_dict(p) for p in plans]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/lesson-plans/<int:plan_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_plan(self, plan_id, **kwargs):
        plan, error = self._authorized_plan(plan_id)
        if error:
            return error
        return api_response(_plan_dict(plan))

    @http.route('/api/v1/lesson-plans', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_plan(self, **kwargs):
        payload = request.get_json_data() or {}
        missing = [f for f in CREATE_FIELDS if not payload.get(f)]
        if missing:
            return api_error('Missing required field(s): %s' % ', '.join(missing), status=400, code='missing_fields')

        vals = {key: payload[key] for key in CREATE_FIELDS}
        faculty = get_own_faculty(request.env)
        if faculty:
            vals['teacher_id'] = faculty.id
        plan, error = safe_create(request.env['bxi.lesson.plan'].sudo(), vals)
        if error:
            return error
        return api_response(_plan_dict(plan), status=201)

    @http.route('/api/v1/lesson-plans/<int:plan_id>/resubmit', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def resubmit_plan(self, plan_id, **kwargs):
        plan, error = self._authorized_plan(plan_id)
        if error:
            return error
        _, error = call_action(plan, 'action_resubmit')
        if error:
            return error
        return api_response(_plan_dict(plan))

    @http.route('/api/v1/lesson-plans/<int:plan_id>/review', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def review_plan(self, plan_id, **kwargs):
        if not _is_coordinator_or_manager(request.env.user):
            return api_error('Not authorized to review lesson plans.', status=403, code='forbidden')
        plan = request.env['bxi.lesson.plan'].sudo().browse(plan_id)
        if not plan.exists():
            return api_error('Lesson plan not found.', status=404, code='not_found')

        payload = request.get_json_data() or {}
        decision = payload.get('decision')
        if decision not in ('approved', 'rejected'):
            return api_error('decision must be "approved" or "rejected".', status=400, code='invalid_decision')

        wizard = request.env['bxi.lesson.plan.review.wizard'].sudo().create({
            'lesson_plan_id': plan.id, 'decision': decision, 'feedback': payload.get('feedback'),
        })
        _, error = call_action(wizard, 'action_confirm')
        if error:
            return error
        return api_response(_plan_dict(plan))

    def _authorized_plan(self, plan_id):
        plan = request.env['bxi.lesson.plan'].sudo().browse(plan_id)
        if not plan.exists():
            return None, api_error('Lesson plan not found.', status=404, code='not_found')
        if _is_coordinator_or_manager(request.env.user) or plan.teacher_id.user_id.id == request.env.user.id:
            return plan, None
        return None, api_error('Not authorized for this lesson plan.', status=403, code='forbidden')
