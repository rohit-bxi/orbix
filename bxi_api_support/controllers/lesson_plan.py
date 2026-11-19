# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Lesson plans (bxi_lesson_plan): the app's Create / Edit Lesson Plan
screens for teachers and academic coordinators, and the coordinators'
review."""
import datetime

from odoo import Command, _, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .academic import _blank, _match_name, _screen_date
from .common import (
    atomic, get_own_faculty, parse_pagination, ref, resolve_record, teacher_permission, json_body,
)

COORDINATOR_GROUP = 'bxi_academic_management.group_academic_coordinator'
MANAGER_GROUP = 'bxi_academic_management.group_academic_manager'

# Payload key (as on the screen) -> field; the second key is the older name.
TEXT_FIELDS = (
    ('topic', None, 'topic'),
    ('learning_objectives', 'objective', 'objective'),
    ('activities', None, 'activities'),
    ('resources', None, 'resources'),
    ('assessment_method', None, 'assessment_method'),
    ('duration', 'duration_label', 'duration_label'),
)
# The screen's "+ Add" lists -> line_type, and whether the screen stars it.
LIST_FIELDS = (
    ('recall_questions', 'recall_question', True),
    ('class_work', 'class_work', True),
    ('teaching_aids', 'teaching_aid', True),
    ('home_work', 'home_work', True),
    ('remarks', 'remark', False),
)
RECORD_FIELDS = (('subject', 'op.subject', 'subject_id'), ('class', 'op.course', 'class_id'))
# "Day and Date" as the screen shows it: "Monday, April 6, 2026".
LONG_DATE_FORMATS = ('%A, %B %d, %Y', '%A, %b %d, %Y', '%B %d, %Y')


def _is_coordinator_or_manager(user):
    return user.has_group(COORDINATOR_GROUP) or user.has_group(MANAGER_GROUP)


def _plan_dict(plan):
    lines = plan.line_ids.sorted(lambda line: (line.sequence, line.id))
    data = {
        'id': plan.id,
        'teacher': plan.teacher_id.display_name,
        'subject': plan.subject_id.display_name,
        'class': plan.class_id.display_name,
        'quarter': plan.quarter_id.display_name,
        'teacher_id': plan.teacher_id.id,
        'subject_id': plan.subject_id.id,
        'class_id': plan.class_id.id,
        'quarter_id': plan.quarter_id.id or None,
        'topic': plan.topic,
        'objective': plan.objective,
        'learning_objectives': plan.objective,
        'activities': plan.activities,
        'resources': plan.resources,
        'assessment_method': plan.assessment_method,
        'duration': plan.duration_label or None,
        'duration_days': plan.duration,
        'start_date': plan.start_date and plan.start_date.isoformat(),
        'end_date': plan.end_date and plan.end_date.isoformat(),
        'plan_date': plan.plan_date and plan.plan_date.isoformat(),
        'plan_day': plan.plan_day or None,
        'state': plan.state,
        'lines': [{'id': line.id, 'line_type': line.line_type, 'name': line.name} for line in lines],
    }
    for key, line_type, _required in LIST_FIELDS:
        data[key] = [{'id': line.id, 'text': line.name} for line in lines if line.line_type == line_type]
    return data


def _missing(key):
    return api_error(f'{key} is required.', status=400, code=f'missing_{key}')


def _plan_date(payload):
    """(date or None when not sent, error): "plan_date" (or "date") as
    DD/MM/YYYY, YYYY-MM-DD or "Monday, April 6, 2026"."""
    key = 'plan_date' if 'plan_date' in payload else ('date' if 'date' in payload else None)
    if not key:
        return None, None
    value = payload[key]
    if isinstance(value, str) and ',' in value:
        for pattern in LONG_DATE_FORMATS:
            try:
                return datetime.datetime.strptime(value.strip(), pattern).date(), None
            except ValueError:
                continue
        return None, api_error('plan_date must be DD/MM/YYYY, YYYY-MM-DD or like "Monday, April 6, 2026".',
                               status=400, code='invalid_plan_date')
    day, error = _screen_date({'plan_date': value}, 'plan_date')
    return day, error


def _list_commands(payload, plan, creating):
    """(line commands, error) for the "+ Add" lists. A list that is sent
    replaces that kind of line; items are strings (or {"text": ...})."""
    commands = []
    for key, line_type, required in LIST_FIELDS:
        if key not in payload:
            if creating and required:
                return None, _missing(key)
            continue
        items = payload[key]
        if items is None:
            items = []
        if isinstance(items, str):
            items = [items]
        if not isinstance(items, list):
            return None, api_error(f'{key} must be a list.', status=400, code=f'invalid_{key}')
        texts = []
        for item in items:
            text = item.get('text', item.get('name')) if isinstance(item, dict) else item
            if not isinstance(text, str):
                return None, api_error(f'Each item of {key} must be text.', status=400, code=f'invalid_{key}')
            if text.strip():
                texts.append(text.strip())
        if required and not texts:
            return None, _missing(key)
        if plan:
            commands += [Command.unlink(line.id) for line in plan.line_ids if line.line_type == line_type]
        commands += [Command.create({'line_type': line_type, 'name': text, 'sequence': index})
                     for index, text in enumerate(texts, start=1)]
    return commands, None


def _record(payload, key, model, field):
    """(record or None when not sent, error): "<key>_id", or "<key>" as
    typed on the screen (name or code, ignoring case)."""
    id_key = f'{key}_id'
    if id_key in payload:
        record, error = resolve_record(request.env, model, payload[id_key], id_key)
        if error:
            return None, error
        return (record, None) if record else (None, _missing(id_key))
    if key in payload:
        if _blank(payload[key]) or not isinstance(payload[key], str):
            return None, _missing(id_key)
        return _match_name(model, payload[key].strip(), key, id_key)
    return None, None


def _plan_vals(payload, plan=None):
    """(vals, error) from the Create / Edit Lesson Plan body (all but the
    teacher). On create every starred field is required."""
    creating = plan is None
    vals = {}
    for key, old_key, field in TEXT_FIELDS:
        sent = key if key in payload else (old_key if old_key and old_key in payload else None)
        if not sent:
            if creating:
                return None, _missing(key)
            continue
        value = payload[sent]
        if not isinstance(value, str) or not value.strip():
            return None, _missing(key)
        vals[field] = value.strip()
    for key, model, field in RECORD_FIELDS:
        record, error = _record(payload, key, model, field)
        if error:
            return None, error
        if record is None:
            if creating:
                return None, _missing(f'{key}_id')
            continue
        vals[field] = record.id
    for key in ('start_date', 'end_date'):
        if key not in payload:
            if creating:
                return None, _missing(key)
            continue
        vals[key], error = _screen_date(payload, key)
        if error:
            return None, error
    day, error = _plan_date(payload)
    if error:
        return None, error
    if day is None and creating:
        return None, _missing('plan_date')
    if day is not None:
        vals['plan_date'] = day
    if 'quarter_id' in payload and payload['quarter_id'] not in (None, ''):
        quarter, error = resolve_record(request.env, 'op.academic.term', payload['quarter_id'], 'quarter_id')
        if error:
            return None, error
        vals['quarter_id'] = quarter.id
    lines, error = _list_commands(payload, plan, creating)
    if error:
        return None, error
    if lines:
        vals['line_ids'] = lines

    # Checks on the values the plan would end up with.
    Plan = request.env['bxi.lesson.plan']
    start = vals.get('start_date', plan.start_date if plan else None)
    end = vals.get('end_date', plan.end_date if plan else None)
    on = vals.get('plan_date', plan.plan_date if plan else None)
    if start and end and end < start:
        return None, api_error('end_date cannot be before start_date.', status=400, code='invalid_dates')
    if on and start and end and not start <= on <= end:
        return None, api_error('The Day and Date must be between the start and end dates.', status=400,
                               code='plan_date_outside_dates')
    course = request.env['op.course'].sudo().browse(vals['class_id']) if 'class_id' in vals else \
        (plan.class_id if plan else None)
    subject = request.env['op.subject'].sudo().browse(vals['subject_id']) if 'subject_id' in vals else \
        (plan.subject_id if plan else None)
    if course and subject and course.subject_ids and subject not in course.subject_ids:
        return None, api_error(f'{subject.name} is not a subject of {course.name}.', status=400,
                               code='subject_not_in_class')
    if creating and not vals.get('quarter_id') and not Plan._bxi_quarter_for(start):
        return None, api_error('No academic term (quarter) covers the start date: add one first.', status=400,
                               code='no_quarter')
    return vals, None


def _teacher(payload, plan=None):
    """(op.faculty or None to keep, error). A teacher's plan is always
    their own; a coordinator or manager names the teacher ("teacher_id",
    or "teacher" as typed - a Dr./Mr./Ms. title is ignored)."""
    env = request.env
    chooses = _is_coordinator_or_manager(env.user)
    named, error = _record(payload, 'teacher', 'op.faculty', 'teacher_id')
    if error:
        return None, error
    if chooses:
        if named:
            return named, None
        if plan:
            return None, None
        own = get_own_faculty(env)
        return (own, None) if own else (None, _missing('teacher_id'))
    own = get_own_faculty(env)
    if not own:
        return None, api_error('Only a teacher or a coordinator can do this.', status=403, code='forbidden')
    if named and named != own:
        return None, api_error('A teacher can only plan their own lessons.', status=403, code='forbidden')
    return (own, None) if not plan else (None, None)


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
    @teacher_permission('lesson_plans')
    def create_plan(self, **kwargs):
        """The Create Lesson Plan screen. Required: teacher (coordinators:
        "teacher_id" or "teacher" as typed; a teacher is always
        themselves), "subject_id" / "subject", "class_id" / "class",
        "duration" (free text, e.g. "5 days"), "topic",
        "learning_objectives", "activities", "resources",
        "assessment_method", "start_date", "end_date", "plan_date" (the
        Day and Date), and at least one item in "recall_questions",
        "class_work", "teaching_aids" and "home_work"; "remarks" is
        optional. Dates as DD/MM/YYYY or YYYY-MM-DD. The quarter is taken
        from the start date unless "quarter_id" is sent."""
        payload = json_body() or {}
        teacher, error = _teacher(payload)
        if error:
            return error
        vals, error = _plan_vals(payload)
        if error:
            return error
        vals['teacher_id'] = teacher.id
        plan, error = atomic(lambda: request.env['bxi.lesson.plan'].sudo().create(vals))
        if error:
            return error
        return api_response(_plan_dict(plan), status=201)

    @http.route('/api/v1/lesson-plans/<int:plan_id>/update', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    @teacher_permission('lesson_plans')
    def update_plan(self, plan_id, **kwargs):
        """The Edit Lesson Plan screen: any create key; only the keys sent
        change, and a list sent replaces that list. Editing an approved
        plan sends it back for review (pending)."""
        plan, error = self._authorized_plan(plan_id)
        if error:
            return error
        payload = json_body() or {}
        teacher, error = _teacher(payload, plan)
        if error:
            return error
        vals, error = _plan_vals(payload, plan)
        if error:
            return error
        if teacher and teacher != plan.teacher_id:
            vals['teacher_id'] = teacher.id
        if not vals:
            return api_response(_plan_dict(plan))
        reapprove = plan.state == 'approved'
        if reapprove:
            vals['state'] = 'pending'

        def write():
            plan.write(vals)
            if reapprove:
                plan.message_post(body=_('Lesson plan edited after approval: sent back for review.'))
            return True

        _result, error = atomic(write)
        if error:
            return error
        return api_response(_plan_dict(plan))

    @http.route('/api/v1/lesson-plans/<int:plan_id>/resubmit', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    @teacher_permission('lesson_plans')
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

        payload = json_body() or {}
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
