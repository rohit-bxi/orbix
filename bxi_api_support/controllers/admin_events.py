# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Admin dashboard - events: every event with seat, registration,
permission-slip and payment figures; an event's detail with its
registrations; creating and editing events, posting the announcement and
taking attendance. The family flow (register, sign, pay) stays on
/events and /event-registrations (event.py)."""
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields, http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, parse_int, require_auth

from ..models.res_users import PERMISSION_GROUPS
from .common import (
    atomic, check_selection, parse_date, parse_datetime, parse_ids, parse_pagination, parse_sort, ref,
    resolve_record, resolve_records, running_enrollments, school_context,
)
from .dashboard import _allowed
from .event import _event_dict, _registration_dict

GROUPS = PERMISSION_GROUPS['event_coordinator']
SORTS = {'date_begin': 'date_begin', 'name': 'name', 'category': 'event_category', 'venue': 'venue_id'}
STATUSES = ('upcoming', 'ongoing', 'past', 'cancelled')
REGISTRATION_STATES = ('draft', 'open', 'done', 'cancel')

# Payload keys - the names the list/detail responses use - to event fields.
TEXT_FIELDS = {'name': 'name', 'description': 'description'}
BOOLEAN_FIELDS = {
    'seats_limited': 'seats_limited', 'is_paid': 'is_paid_event',
    'requires_permission_slip': 'requires_permission_slip', 'offers_transport': 'requires_transport',
}
SELECTION_FIELDS = {'category': 'event_category', 'target_audience': 'target_audience', 'timezone': 'date_tz'}
RECORD_FIELDS = {
    'venue_id': 'bxi.event.venue', 'fee_product_id': 'product.product',
    'academic_year_id': 'op.academic.year', 'academic_term_id': 'op.academic.term',
}
MANY_FIELDS = {'course_ids': 'op.course', 'batch_ids': 'op.batch', 'coordinator_ids': 'op.faculty'}


def _forbidden():
    return api_error('Not authorized for event administration.', status=403, code='forbidden')


def _status(event, now):
    if event.kanban_state == 'cancel':
        return 'cancelled'
    if event.date_end <= now:
        return 'past'
    if event.date_begin <= now:
        return 'ongoing'
    return 'upcoming'


def _status_domain(status, now):
    live = Domain('kanban_state', '!=', 'cancel')
    return {
        'upcoming': live & Domain('date_begin', '>', now),
        'ongoing': live & Domain('date_begin', '<=', now) & Domain('date_end', '>', now),
        'past': live & Domain('date_end', '<=', now),
        'cancelled': Domain('kanban_state', '=', 'cancel'),
    }[status]


def _payment(registrations):
    """Money on a paid event's live registrations: posted invoices'
    total/collected/pending, and how many have no invoice yet (the invoice
    is raised on the first confirm)."""
    invoices = registrations.invoice_id.filtered(lambda move: move.state == 'posted')
    invoiced = sum(invoices.mapped('amount_total'))
    pending = sum(invoices.mapped('amount_residual'))
    return {
        'invoiced': invoiced,
        'collected': invoiced - pending,
        'pending': pending,
        'not_invoiced': len(registrations.filtered(lambda r: not r.invoice_id)),
    }


def _event_row(event, registrations, now):
    registrations = registrations.filtered(lambda r: r.event_id == event)
    live = registrations.filtered(lambda r: r.state != 'cancel')
    counts = {state: len(registrations.filtered(lambda r, s=state: r.state == s)) for state in REGISTRATION_STATES}
    announcement = event.announcement_id
    return dict(
        _event_dict(event),
        status=_status(event, now),
        classes=[ref(c) for c in event.course_ids],
        sections=[ref(b) for b in event.batch_ids],
        coordinators=[ref(f) for f in event.coordinator_ids],
        seats_max=event.seats_max if event.seats_limited else None,
        seats_taken=event.seats_taken,
        registration_counts=dict(counts, total=len(live)),
        permission_slips_pending=len(live.filtered(lambda r: not r.permission_slip_signed))
        if event.requires_permission_slip else 0,
        payment=_payment(live) if event.is_paid_event else None,
        announcement={'id': announcement.id, 'state': announcement.state} if announcement else None,
    )


def _event_vals(env, payload):
    """(vals, error) for an event.event create/write."""
    Event = env['event.event']
    vals = {}
    for key, field in TEXT_FIELDS.items():
        if key in payload:
            if key == 'name' and not payload[key]:
                return None, api_error('name cannot be empty.', status=400, code='missing_name')
            vals[field] = payload[key] or False
    for key, field in BOOLEAN_FIELDS.items():
        if key in payload:
            vals[field] = bool(payload[key])
    for key, field in SELECTION_FIELDS.items():
        if key in payload:
            error = check_selection(Event, field, payload[key], key)
            if error:
                return None, error
            vals[field] = payload[key]
    for key, model in RECORD_FIELDS.items():
        if key in payload:
            record, error = resolve_record(env, model, payload[key], key)
            if error:
                return None, error
            vals[key] = record.id or False
    for key, model in MANY_FIELDS.items():
        if key in payload:
            records, error = resolve_records(env, model, payload[key], key)
            if error:
                return None, error
            vals[key] = [(6, 0, records.ids)]
    for key in ('date_begin', 'date_end'):
        if key in payload:
            vals[key], error = parse_datetime(payload[key], key)
            if error:
                return None, error
    if 'seats_max' in payload:
        seats, error = parse_int(payload['seats_max'] or 0, 'seats_max')
        if error:
            return None, error
        if seats < 0:
            return None, api_error('seats_max cannot be negative.', status=400, code='invalid_seats_max')
        vals['seats_max'] = seats
    return vals, None


class BxiApiSupportAdminEventsController(http.Controller):

    def _get_event(self, event_id):
        event = request.env['event.event'].sudo().browse(event_id)
        if not event.exists():
            return None, api_error('Event not found.', status=404, code='not_found')
        return event, None

    def _event_detail(self, event):
        now = fields.Datetime.now()
        registrations = event.registration_ids.sorted(lambda r: (r.student_id.name or r.name or '', r.id))
        enrollments = running_enrollments(request.env, registrations.student_id)
        rows = []
        for reg in registrations:
            enrollment = enrollments.get(reg.student_id.id)
            rows.append(dict(
                _registration_dict(reg),
                name=reg.name,
                **{'class': ref(enrollment.course_id) if enrollment else None},
                section=ref(enrollment.batch_id) if enrollment else None,
                parent=ref(reg.parent_id),
                attended=reg.state == 'done',
            ))
        return dict(
            _event_row(event, event.registration_ids, now),
            description=event.description or None,
            timezone=event.date_tz,
            academic_year=ref(event.academic_year_id),
            academic_term=ref(event.academic_term_id),
            fee_product=ref(event.fee_product_id),
            registrations=rows,
        )

    @http.route('/api/v1/admin/events', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_events(self, q=None, category=None, status=None, date_from=None, date_to=None, sort=None, **kwargs):
        """Every event with its figures. Filters: q, category, status
        (upcoming/ongoing/past/cancelled), date_from/date_to (events
        overlapping those UTC days), venue_id, course_id, batch_id,
        academic_year_id. The summary covers every matching event."""
        env = request.env
        if not _allowed(env.user, GROUPS):
            return _forbidden()
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        order, error = parse_sort(sort, SORTS, 'date_begin desc')
        if error:
            return error
        now = fields.Datetime.now()
        domain = Domain.TRUE
        if q:
            domain &= Domain('name', 'ilike', q)
        if category:
            error = check_selection(env['event.event'], 'event_category', category, 'category')
            if error:
                return error
            domain &= Domain('event_category', '=', category)
        if status:
            if status not in STATUSES:
                return api_error('status must be one of %s.' % ', '.join(STATUSES), status=400, code='invalid_status')
            domain &= _status_domain(status, now)
        for param, field in (('venue_id', 'venue_id'), ('academic_year_id', 'academic_year_id'),
                             ('course_id', 'course_ids'), ('batch_id', 'batch_ids')):
            if kwargs.get(param):
                value, error = parse_int(kwargs[param], param)
                if error:
                    return error
                domain &= Domain(field, 'in', [value])
        if date_from:
            start, error = parse_date(date_from, 'date_from')
            if error:
                return error
            domain &= Domain('date_end', '>=', fields.Datetime.to_datetime(start))
        if date_to:
            end, error = parse_date(date_to, 'date_to')
            if error:
                return error
            domain &= Domain('date_begin', '<', fields.Datetime.to_datetime(end) + timedelta(days=1))
        Event = env['event.event'].sudo()
        events = Event.search(domain, order='%s %s, id %s' % (SORTS[order[0]], order[1], order[1]))
        registrations = env['event.registration'].sudo().search([('event_id', 'in', events.ids)])
        live = registrations.filtered(lambda r: r.state != 'cancel')
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = month_start + relativedelta(months=1)
        slip_events = events.filtered('requires_permission_slip')
        paid_events = events.filtered('is_paid_event')
        return api_response({
            'items': [_event_row(e, registrations, now) for e in events[offset:offset + limit]],
            'summary': {
                'events': len(events),
                'upcoming': len(events.filtered(lambda e: _status(e, now) == 'upcoming')),
                'this_month': len(events.filtered(lambda e: month_start <= e.date_begin < month_end)),
                'registrations': len(live),
                'attended': len(live.filtered(lambda r: r.state == 'done')),
                'permission_slips_pending': len(live.filtered(
                    lambda r: r.event_id in slip_events and not r.permission_slip_signed)),
                'payment_pending': _payment(live.filtered(lambda r: r.event_id in paid_events))['pending'],
            },
        }, meta={'total': len(events), 'limit': limit, 'offset': offset})

    @http.route('/api/v1/admin/events/options', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def options(self, **kwargs):
        """Choices for the event form and filters. Venues, classes,
        sections and teachers come from /masters; fee products from the
        staff-only service-products master."""
        env = request.env
        if not _allowed(env.user, GROUPS):
            return _forbidden()
        described = env['event.event'].fields_get(['event_category', 'target_audience'], ['selection'])
        return api_response({
            'categories': [{'value': v, 'label': l} for v, l in described['event_category']['selection']],
            'audiences': [{'value': v, 'label': l} for v, l in described['target_audience']['selection']],
            'statuses': list(STATUSES),
            'default_timezone': env.user.tz or 'UTC',
        })

    @http.route('/api/v1/admin/events/<int:event_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_event(self, event_id, **kwargs):
        if not _allowed(request.env.user, GROUPS):
            return _forbidden()
        event, error = self._get_event(event_id)
        if error:
            return error
        return api_response(self._event_detail(event))

    @http.route('/api/v1/admin/events', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_event(self, **kwargs):
        """{"name", "date_begin", "date_end" (UTC, YYYY-MM-DD HH:MM:SS),
        "category"?, "target_audience"?, "course_ids"?, "batch_ids"?,
        "coordinator_ids"?, "venue_id"?, "seats_limited"?, "seats_max"?,
        "is_paid"?, "fee_product_id"? (needed when paid),
        "requires_permission_slip"?, "offers_transport"?, "description"?,
        "timezone"?, "academic_year_id"?, "academic_term_id"?}"""
        env = request.env
        if not _allowed(env.user, GROUPS):
            return _forbidden()
        payload = request.get_json_data() or {}
        for required in ('name', 'date_begin', 'date_end'):
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        vals, error = _event_vals(env, payload)
        if error:
            return error
        event, error = atomic(lambda: env['event.event'].sudo().create(vals))
        if error:
            return error
        return api_response(self._event_detail(event), status=201)

    @http.route('/api/v1/admin/events/<int:event_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_event(self, event_id, **kwargs):
        """Any create field; only the ones sent change."""
        env = request.env
        if not _allowed(env.user, GROUPS):
            return _forbidden()
        event, error = self._get_event(event_id)
        if error:
            return error
        vals, error = _event_vals(env, request.get_json_data() or {})
        if error:
            return error
        _, error = atomic(lambda: event.write(vals))
        if error:
            return error
        return api_response(self._event_detail(event))

    @http.route('/api/v1/admin/events/<int:event_id>/post-announcement', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def post_announcement(self, event_id, **kwargs):
        """Creates the event's announcement (same audience) as a draft -
        publish it with /announcements/<id>/publish. Calling again returns
        the existing one."""
        if not _allowed(request.env.user, GROUPS):
            return _forbidden()
        event, error = self._get_event(event_id)
        if error:
            return error
        existed = bool(event.announcement_id)
        _, error = call_action(event, 'action_post_announcement')
        if error:
            return error
        announcement = event.announcement_id
        return api_response({
            'event_id': event.id,
            'announcement': {'id': announcement.id, 'title': announcement.title, 'state': announcement.state},
        }, status=200 if existed else 201)

    @http.route('/api/v1/admin/events/<int:event_id>/attendance', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def attendance(self, event_id, **kwargs):
        """{"registration_ids": [...], "attended": true} marks those
        confirmed registrations attended ("attended": false undoes it).
        Event coordinators and the event's duty teachers. Unconfirmed
        (unpaid/unsigned) or cancelled registrations are refused."""
        env = request.env
        event, error = self._get_event(event_id)
        if error:
            return error
        if not (_allowed(env.user, GROUPS) or school_context(env)['faculty'] in event.coordinator_ids):
            return _forbidden()
        payload = request.get_json_data() or {}
        ids, error = parse_ids(payload.get('registration_ids') or [], 'registration_ids')
        if error:
            return error
        if not ids:
            return api_error('registration_ids is required.', status=400, code='missing_registration_ids')
        registrations, error = resolve_records(env, 'event.registration', ids, 'registration_ids')
        if error:
            return error
        if registrations.event_id != event:
            return api_error('Every registration must belong to this event.', status=400, code='not_in_event')
        not_confirmed = registrations.filtered(lambda r: r.state not in ('open', 'done'))
        if not_confirmed:
            return api_error('Registrations %s are not confirmed.' % not_confirmed.ids,
                             status=400, code='not_confirmed')
        attended = payload.get('attended', True)
        if attended:
            _, error = atomic(lambda: registrations.filtered(lambda r: r.state == 'open').action_set_done())
        else:
            _, error = atomic(lambda: registrations.filtered(lambda r: r.state == 'done').write({'state': 'open'}))
        if error:
            return error
        return api_response({
            'event_id': event.id,
            'registrations': [dict(_registration_dict(r), attended=r.state == 'done') for r in registrations],
            'registration_counts': _event_row(event, event.registration_ids, fields.Datetime.now())['registration_counts'],
        })
