# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Academic coordinators' set-up (bxi_academic_management): scheduling
parent-teacher meetings and the school's holidays. Reading them stays in
academic.py and calendar.py. Saving a PTM notifies the parents and
teachers of its classes (the model does that on create/write)."""
import re
from datetime import datetime, time, timedelta

import pytz

from odoo import Command, fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth

from .academic import _chips, _is_coordinator_or_manager, _ptm_dict, _screen_date
from .common import atomic, date_str, parse_datetime, parse_int, ref, json_body


def _forbidden():
    return api_error('Only academic coordinators can do this.', status=403, code='forbidden')


def _allowed(user):
    return user.has_group('base.group_system') or _is_coordinator_or_manager(user)


DEFAULT_PTM_MINUTES = 60
# "10:15 AM", "10 : 15 : AM" (as the screen's picker shows it), "10:15", "22:15:00".
TIME_PATTERN = re.compile(r'^(\d{1,2}):(\d{2})(?::(\d{2}))?:?(AM|PM)?$', re.IGNORECASE)


def _ptm_detail(meeting):
    data = _ptm_dict(meeting)
    start = _local(meeting.env, meeting.start_datetime)
    end = _local(meeting.env, meeting.end_datetime)
    data.update({
        'class_ids': meeting.class_ids.ids,
        'classes_detail': [ref(c) for c in meeting.class_ids],
        'section_ids': meeting.batch_ids.ids,
        'sections': [ref(b) for b in meeting.batch_ids],
        # The screen's Date and Time, in the school's time zone.
        'date': date_str(start.date()) if start else None,
        'time': start.strftime('%H:%M') if start else None,
        'time_label': start.strftime('%I:%M %p') if start else None,
        'duration_minutes': int((end - start).total_seconds() // 60) if start and end else None,
        'active': meeting.active,
        'parents_notified': len(meeting.parent_ids),
        'teachers_notified': len(meeting.teacher_ids),
    })
    return data


def _local(env, value):
    return pytz.utc.localize(value).astimezone(_school_tz(env)).replace(tzinfo=None) if value else None


def _parse_time(value):
    """(datetime.time, None) or (None, api_error(...))."""
    text = re.sub(r'\s+', '', str(value or ''))
    match = TIME_PATTERN.match(text)
    error = api_error('time must look like 10:15 AM or 22:15.', status=400, code='invalid_time')
    if not match:
        return None, error
    hour, minute, second, half = int(match[1]), int(match[2]), int(match[3] or 0), (match[4] or '').upper()
    if half:
        if not 1 <= hour <= 12:
            return None, error
        hour = hour % 12 + (12 if half == 'PM' else 0)
    if hour > 23 or minute > 59 or second > 59:
        return None, error
    return time(hour, minute, second), None


def _ptm_vals(env, payload, meeting=None):
    """(vals, error) for the Schedule / Edit Schedule PTM screens.

    When: "date" (DD/MM/YYYY or YYYY-MM-DD) and "time" ("10:15 AM") in the
    school's time zone, with "duration_minutes"? (default 60; on edit the
    meeting keeps its length), or "start_datetime" / "end_datetime" in
    UTC. Who: "section_ids" / "sections" (the "Class 10 A" chips) and/or
    "class_ids" / "classes" (whole classes), or add_/remove_ lists of
    either; a section's class is added for it."""
    vals = {}
    for key in ('name', 'venue'):
        if key in payload:
            if not isinstance(payload[key], str) or not payload[key].strip():
                return None, api_error(f'{key} cannot be empty.', status=400, code=f'missing_{key}')
            vals[key] = payload[key].strip()
    for key in ('start_datetime', 'end_datetime'):
        if key in payload:
            vals[key], error = parse_datetime(payload[key], key)
            if error or not vals[key]:
                return None, error or api_error(f'{key} is required.', status=400, code=f'missing_{key}')
    if 'date' in payload or 'time' in payload:
        current = _local(env, meeting.start_datetime) if meeting else None
        day, error = _screen_date(payload, 'date') if 'date' in payload else (current and current.date(), None)
        if error:
            return None, error
        if 'time' in payload:
            at, error = _parse_time(payload['time'])
            if error:
                return None, error
        else:
            at = current and current.time()
        if not day:
            return None, api_error('date is required.', status=400, code='missing_date')
        if at is None:
            return None, api_error('time is required.', status=400, code='missing_time')
        start = _school_tz(env).localize(datetime.combine(day, at)).astimezone(pytz.utc).replace(tzinfo=None)
        vals['start_datetime'] = start
    if 'duration_minutes' in payload:
        minutes, error = parse_int(payload['duration_minutes'], 'duration_minutes')
        if error:
            return None, error
        if minutes <= 0:
            return None, api_error('duration_minutes must be positive.', status=400, code='invalid_duration_minutes')
    elif meeting and meeting.start_datetime and meeting.end_datetime:
        minutes = int((meeting.end_datetime - meeting.start_datetime).total_seconds() // 60)
    else:
        minutes = DEFAULT_PTM_MINUTES
    if 'end_datetime' not in vals and ('start_datetime' in vals or 'duration_minutes' in payload):
        start = vals.get('start_datetime') or meeting.start_datetime
        vals['end_datetime'] = start + timedelta(minutes=minutes)

    classes, error = _chips(payload, 'op.course', 'class', meeting.class_ids if meeting else None)
    if error:
        return None, error
    sections, error = _chips(payload, 'op.batch', 'section', meeting.batch_ids if meeting else None)
    if error:
        return None, error
    if classes is not None or sections is not None:
        if sections is not None:
            final_sections = sections
        elif meeting:
            # Classes taken off take their sections with them.
            final_sections = meeting.batch_ids.filtered(lambda b: b.course_id in classes)
        else:
            final_sections = env['op.batch']
        if classes is not None:
            final_classes = classes
        elif meeting:
            # New sections replace the old ones' classes; whole classes stay.
            final_classes = meeting.class_ids - meeting.batch_ids.course_id
        else:
            final_classes = env['op.course']
        final_classes |= final_sections.course_id
        if not final_classes:
            return None, api_error('Add at least one class.', status=400, code='missing_class_ids')
        vals['class_ids'] = [Command.set(final_classes.ids)]
        vals['batch_ids'] = [Command.set(final_sections.ids)]
    return vals, None


def _school_tz(env):
    return pytz.timezone(env.company.resource_calendar_id.tz or env.user.tz or 'UTC')


def _holiday_bound(env, value, key, end=False):
    """A holiday edge from a day - DD/MM/YYYY as on the screen, or
    YYYY-MM-DD: the whole day in the school's time zone - or a UTC
    date-time. Returns (naive UTC datetime, None) or (None, api_error(...))."""
    if value in (None, '') or (isinstance(value, str) and not value.strip()):
        return None, api_error(f'{key} is required.', status=400, code=f'missing_{key}')
    text = str(value).strip()
    if len(text) == 10:
        try:
            day = datetime.strptime(text, '%d/%m/%Y').date() if '/' in text else fields.Date.to_date(text)
        except ValueError:
            return None, api_error(f'{key} must be DD/MM/YYYY, YYYY-MM-DD or a UTC date-time.', status=400,
                                   code=f'invalid_{key}')
        local = _school_tz(env).localize(datetime.combine(day, time.max.replace(microsecond=0) if end else time.min))
        return local.astimezone(pytz.utc).replace(tzinfo=None), None
    return parse_datetime(text, key)


def _holiday_dict(leave):
    """One shape for the list, get, create and update: start_date /
    end_date are the holiday's days in the school's time zone (what the
    Add / Edit Holiday screens show); date_from / date_to are the stored
    UTC bounds."""
    tz = _school_tz(leave.env)
    start = pytz.utc.localize(leave.date_from).astimezone(tz).date() if leave.date_from else None
    end = pytz.utc.localize(leave.date_to).astimezone(tz).date() if leave.date_to else None
    return {
        'id': leave.id,
        'name': leave.name,
        'description': leave.description or None,
        'start_date': date_str(start),
        'end_date': date_str(end),
        'date_from': date_str(leave.date_from),
        'date_to': date_str(leave.date_to),
        'first_day': date_str(start),
        'last_day': date_str(end),
    }


# Screen key -> stored bound, with the older key each one stands for.
HOLIDAY_BOUNDS = (('start_date', 'date_from', False), ('end_date', 'date_to', True))

# A public holiday makes hr_holidays recount the time off it overlaps and
# put each request back in its state. For a double-approved request that
# re-checks the *current user's* time-off rights, even under sudo(), so a
# coordinator who is not a time-off officer could not add a holiday over
# one (403). leave_fast_create is the flag Odoo itself sets for such
# system-driven writes: it skips only the approval checks, followers and
# activities; allocations are still re-checked.
HOLIDAY_CONTEXT = {'leave_fast_create': True}


def _holiday_model(env):
    return env['resource.calendar.leaves'].sudo().with_context(**HOLIDAY_CONTEXT)


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
        """The Schedule PTM screen: "name", "date" + "time" (or
        "start_datetime" in UTC), "venue", and "section_ids" / "sections"
        and/or "class_ids" / "classes" - see _ptm_vals. Parents of the
        invited students and the classes' teachers are notified."""
        env = request.env
        if not _allowed(env.user):
            return _forbidden()
        payload = json_body() or {}
        for key in ('name', 'venue'):
            if key not in payload:
                return api_error(f'{key} is required.', status=400, code=f'missing_{key}')
        if 'start_datetime' not in payload:
            for key in ('date', 'time'):
                if key not in payload:
                    return api_error(f'{key} is required.', status=400, code=f'missing_{key}')
        if not any(key in payload for key in ('class_ids', 'class_id', 'classes', 'section_ids', 'section_id',
                                              'sections')):
            return api_error('Add at least one class.', status=400, code='missing_class_ids')
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
        vals, error = _ptm_vals(env, json_body() or {}, meeting)
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
        """(vals, error) for the Add / Edit Holiday screens: "name",
        "start_date" / "end_date" (or "date_from" / "date_to"),
        "description"."""
        vals = {}
        if 'name' in payload:
            name = payload['name']
            if not isinstance(name, str) or not name.strip():
                return None, api_error('name cannot be empty.', status=400, code='missing_name')
            vals['name'] = name.strip()
        if 'description' in payload:
            description = payload['description']
            vals['description'] = description.strip() if isinstance(description, str) and description.strip() \
                else False
        for key, field, end in HOLIDAY_BOUNDS:
            sent = key if key in payload else (field if field in payload else None)
            if sent:
                vals[field], error = _holiday_bound(env, payload[sent], sent, end=end)
                if error:
                    return None, error
        start = vals.get('date_from') or (leave.date_from if leave else None)
        finish = vals.get('date_to') or (leave.date_to if leave else None)
        if start and finish and finish <= start:
            return None, api_error('end_date cannot be before start_date.', status=400, code='invalid_dates')
        name = vals.get('name') or (leave.name if leave else None)
        if start and finish:
            # hr_holidays allows no two public holidays on the same dates
            # (a 400 with its own wording otherwise): say which one is there.
            domain = [('resource_id', '=', False), ('company_id', '=', env.company.id),
                      ('date_from', '<=', finish), ('date_to', '>=', start)]
            if leave:
                domain.append(('id', '!=', leave.id))
            existing = env['resource.calendar.leaves'].sudo().search(domain, limit=1)
            if existing:
                same = bool(name) and existing.name.strip().lower() == name.strip().lower()
                message = f'{existing.name} is already a holiday on these dates.' if same else \
                    f'These dates overlap {existing.name}: two holidays cannot share a day.'
                return None, request.make_json_response({'success': False, 'error': {
                    'message': message, 'code': 'holiday_exists' if same else 'holiday_overlaps',
                    'existing_holiday_id': existing.id}}, status=409)
        return vals, None

    @http.route('/api/v1/calendar/holidays/<int:leave_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_holiday(self, leave_id, **kwargs):
        """The Edit Holiday screen's pre-fill. Holidays are school-wide, so
        anyone signed in may read one, as with the list."""
        leave, error = self._holiday(leave_id)
        if error:
            return error
        return api_response(_holiday_dict(leave))

    @http.route('/api/v1/calendar/holidays', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_holiday(self, **kwargs):
        """The Add Holiday screen: {"name", "start_date", "end_date",
        "description"?} - days as DD/MM/YYYY or YYYY-MM-DD, whole days in
        the school's time zone ("date_from" / "date_to", and UTC
        date-times, still work). A school-wide closure: it shows on every
        family's and teacher's calendar. 409 holiday_exists (same name) or
        holiday_overlaps (another holiday) on overlapping dates."""
        env = request.env
        if not _allowed(env.user):
            return _forbidden()
        payload = json_body() or {}
        if 'name' not in payload:
            return api_error('name is required.', status=400, code='missing_name')
        for key, field, _end in HOLIDAY_BOUNDS:
            if key not in payload and field not in payload:
                return api_error(f'{key} is required.', status=400, code=f'missing_{key}')
        vals, error = self._holiday_vals(env, payload)
        if error:
            return error
        vals.update(resource_id=False, calendar_id=False, company_id=env.company.id)
        leave, error = atomic(lambda: _holiday_model(env).create(vals))
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
        vals, error = self._holiday_vals(env, json_body() or {}, leave)
        if error:
            return error
        _, error = atomic(lambda: leave.with_context(**HOLIDAY_CONTEXT).write(vals))
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
        _, error = atomic(leave.with_context(**HOLIDAY_CONTEXT).unlink)
        if error:
            return error
        return api_response({'id': leave_id, 'deleted': True})
