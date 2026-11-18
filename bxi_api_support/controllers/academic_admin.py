# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Academic coordinators' set-up (bxi_academic_management): scheduling
parent-teacher meetings and the school's holidays. Reading them stays in
academic.py and calendar.py. Saving a PTM notifies the parents and
teachers of its classes (the model does that on create/write)."""
from datetime import datetime, time

import pytz

from odoo import Command, fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth

from .academic import _is_coordinator_or_manager, _ptm_dict
from .common import atomic, date_str, parse_datetime, resolve_records


def _forbidden():
    return api_error('Only academic coordinators can do this.', status=403, code='forbidden')


def _allowed(user):
    return user.has_group('base.group_system') or _is_coordinator_or_manager(user)


def _ptm_detail(meeting):
    data = _ptm_dict(meeting)
    data.update({
        'class_ids': meeting.class_ids.ids,
        'active': meeting.active,
        'parents_notified': len(meeting.parent_ids),
        'teachers_notified': len(meeting.teacher_ids),
    })
    return data


def _ptm_vals(env, payload):
    vals = {}
    for key in ('name', 'venue'):
        if key in payload:
            if not payload[key]:
                return None, api_error(f'{key} cannot be empty.', status=400, code=f'missing_{key}')
            vals[key] = payload[key]
    for key in ('start_datetime', 'end_datetime'):
        if key in payload:
            vals[key], error = parse_datetime(payload[key], key)
            if error or not vals[key]:
                return None, error or api_error(f'{key} is required.', status=400, code=f'missing_{key}')
    if 'class_ids' in payload:
        classes, error = resolve_records(env, 'op.course', payload['class_ids'], 'class_ids')
        if error:
            return None, error
        if not classes:
            return None, api_error('class_ids cannot be empty.', status=400, code='missing_class_ids')
        vals['class_ids'] = [Command.set(classes.ids)]
    return vals, None


def _school_tz(env):
    return pytz.timezone(env.company.resource_calendar_id.tz or env.user.tz or 'UTC')


def _holiday_bound(env, value, key, end=False):
    """A holiday edge from 'YYYY-MM-DD' (the whole day in the school's
    time zone) or a UTC date-time. Returns (naive UTC datetime, None) or
    (None, api_error(...))."""
    if value in (None, ''):
        return None, api_error(f'{key} is required.', status=400, code=f'missing_{key}')
    text = str(value).strip()
    if len(text) == 10:
        try:
            day = fields.Date.to_date(text)
        except ValueError:
            return None, api_error(f'{key} must be YYYY-MM-DD or a UTC date-time.', status=400, code=f'invalid_{key}')
        local = _school_tz(env).localize(datetime.combine(day, time.max.replace(microsecond=0) if end else time.min))
        return local.astimezone(pytz.utc).replace(tzinfo=None), None
    return parse_datetime(text, key)


def _holiday_dict(leave):
    tz = _school_tz(leave.env)
    start = pytz.utc.localize(leave.date_from).astimezone(tz).date() if leave.date_from else None
    end = pytz.utc.localize(leave.date_to).astimezone(tz).date() if leave.date_to else None
    return {
        'id': leave.id,
        'name': leave.name,
        'description': leave.description or None,
        'date_from': date_str(leave.date_from),
        'date_to': date_str(leave.date_to),
        'first_day': date_str(start),
        'last_day': date_str(end),
    }


class BxiApiSupportAcademicAdminController(http.Controller):

    # -- parent-teacher meetings -------------------------------------------------

    def _meeting(self, meeting_id):
        meeting = request.env['bxi.ptm.meeting'].sudo().with_context(active_test=False).browse(meeting_id)
        if not meeting.exists():
            return None, api_error('PTM meeting not found.', status=404, code='not_found')
        return meeting, None

    @http.route('/api/v1/academic/ptm-meetings', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_ptm(self, **kwargs):
        """{"name", "start_datetime", "end_datetime" (UTC), "venue",
        "class_ids"} - parents of the classes' students and their teachers
        are notified."""
        env = request.env
        if not _allowed(env.user):
            return _forbidden()
        payload = request.get_json_data() or {}
        for key in ('name', 'start_datetime', 'end_datetime', 'venue', 'class_ids'):
            if not payload.get(key):
                return api_error(f'{key} is required.', status=400, code=f'missing_{key}')
        vals, error = _ptm_vals(env, payload)
        if error:
            return error
        meeting, error = atomic(lambda: env['bxi.ptm.meeting'].sudo().create(vals))
        if error:
            return error
        return api_response(_ptm_detail(meeting), status=201)

    @http.route('/api/v1/academic/ptm-meetings/<int:meeting_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_ptm(self, meeting_id, **kwargs):
        """Any create field. Changing the time, venue or classes notifies
        everyone again."""
        env = request.env
        if not _allowed(env.user):
            return _forbidden()
        meeting, error = self._meeting(meeting_id)
        if error:
            return error
        vals, error = _ptm_vals(env, request.get_json_data() or {})
        if error:
            return error
        _, error = atomic(lambda: meeting.write(vals))
        if error:
            return error
        return api_response(_ptm_detail(meeting))

    @http.route('/api/v1/academic/ptm-meetings/<int:meeting_id>/<any("archive", "restore"):action>',
                type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def archive_ptm(self, meeting_id, action, **kwargs):
        """Cancel a meeting (archive: it leaves every list) or bring it back."""
        if not _allowed(request.env.user):
            return _forbidden()
        meeting, error = self._meeting(meeting_id)
        if error:
            return error
        meeting.active = action == 'restore'
        return api_response(_ptm_detail(meeting))

    # -- holidays ------------------------------------------------------------------

    def _holiday(self, leave_id):
        leave = request.env['resource.calendar.leaves'].sudo().browse(leave_id)
        if not leave.exists() or leave.resource_id or leave.calendar_id:
            return None, api_error('Holiday not found.', status=404, code='not_found')
        return leave, None

    def _holiday_vals(self, env, payload, leave=None):
        vals = {}
        if 'name' in payload:
            if not payload['name']:
                return None, api_error('name cannot be empty.', status=400, code='missing_name')
            vals['name'] = payload['name']
        if 'description' in payload:
            vals['description'] = payload['description'] or False
        for key, end in (('date_from', False), ('date_to', True)):
            if key in payload:
                vals[key], error = _holiday_bound(env, payload[key], key, end=end)
                if error:
                    return None, error
        start = vals.get('date_from') or (leave.date_from if leave else None)
        finish = vals.get('date_to') or (leave.date_to if leave else None)
        if start and finish and finish <= start:
            return None, api_error('date_to must be after date_from.', status=400, code='invalid_dates')
        return vals, None

    @http.route('/api/v1/calendar/holidays', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_holiday(self, **kwargs):
        """{"name", "date_from", "date_to", "description"?} - whole days as
        YYYY-MM-DD (school time zone), or UTC date-times. A school-wide
        closure: it shows on every family's and teacher's calendar."""
        env = request.env
        if not _allowed(env.user):
            return _forbidden()
        payload = request.get_json_data() or {}
        for key in ('name', 'date_from', 'date_to'):
            if not payload.get(key):
                return api_error(f'{key} is required.', status=400, code=f'missing_{key}')
        vals, error = self._holiday_vals(env, payload)
        if error:
            return error
        vals.update(resource_id=False, calendar_id=False, company_id=env.company.id)
        leave, error = atomic(lambda: env['resource.calendar.leaves'].sudo().create(vals))
        if error:
            return error
        return api_response(_holiday_dict(leave), status=201)

    @http.route('/api/v1/calendar/holidays/<int:leave_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_holiday(self, leave_id, **kwargs):
        env = request.env
        if not _allowed(env.user):
            return _forbidden()
        leave, error = self._holiday(leave_id)
        if error:
            return error
        vals, error = self._holiday_vals(env, request.get_json_data() or {}, leave)
        if error:
            return error
        _, error = atomic(lambda: leave.write(vals))
        if error:
            return error
        return api_response(_holiday_dict(leave))

    @http.route('/api/v1/calendar/holidays/<int:leave_id>/delete', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def delete_holiday(self, leave_id, **kwargs):
        if not _allowed(request.env.user):
            return _forbidden()
        leave, error = self._holiday(leave_id)
        if error:
            return error
        leave.unlink()
        return api_response({'id': leave_id, 'deleted': True})
