# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""School events (bxi_school_event_management): the family's event list,
registration, permission slip and transport add-on - the app counterpart
of the /my/events portal page."""
from odoo import fields, http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, parse_int, require_auth

from .common import (
    audience_domain, date_str, get_viewable_student, parse_pagination, ref, safe_create, school_context,
)

COORDINATOR_GROUP = 'bxi_school_event_management.group_school_event_coordinator'
# Same audience mapping as the portal's _eligible_events_domain, plus
# teachers for staff-facing events.
AUDIENCES_BY_ROLE = {
    '*': ('everyone',),
    'student': ('all_students',),
    'parent': ('all_parents', 'all_students'),
    'teacher': ('all_teachers',),
    'staff': ('all_teachers',),
}


def _is_coordinator(user):
    return user.has_group(COORDINATOR_GROUP)


def _visible_domain(env):
    if _is_coordinator(env.user):
        return Domain.TRUE
    return audience_domain(env, AUDIENCES_BY_ROLE)


def _registration_dict(reg):
    event = reg.event_id
    return {
        'id': reg.id,
        'event_id': event.id,
        'student': ref(reg.student_id),
        'state': reg.state,
        'permission_slip_required': event.requires_permission_slip,
        'permission_slip_signed': reg.permission_slip_signed,
        'signed_by': reg.signed_by or None,
        'payment_required': event.is_paid_event,
        'invoice': {'id': reg.invoice_id.id, 'name': reg.invoice_id.name,
                    'amount': reg.invoice_id.amount_total,
                    'payment_state': reg.invoice_payment_state} if reg.invoice_id else None,
        'transport_registration_id': reg.transport_registration_id.id or None,
    }


def _event_dict(event, registrations=None, detail=False):
    data = {
        'id': event.id,
        'name': event.name,
        'category': event.event_category,
        'date_begin': date_str(event.date_begin),
        'date_end': date_str(event.date_end),
        'venue': ref(event.venue_id),
        'target_audience': event.target_audience,
        'seats_limited': event.seats_limited,
        'seats_available': event.seats_available if event.seats_limited else None,
        'is_paid': event.is_paid_event,
        'fee_amount': event.fee_product_id.lst_price if event.is_paid_event else 0.0,
        'requires_permission_slip': event.requires_permission_slip,
        'offers_transport': event.requires_transport,
        'is_finished': event.is_finished,
    }
    if registrations is not None:
        data['registrations'] = [_registration_dict(r) for r in registrations.filtered(lambda r: r.event_id == event)]
    if detail:
        data['description'] = event.description or None
        data['coordinators'] = [ref(c) for c in event.coordinator_ids]
    return data


def _family_registrations(env, events=None):
    students = school_context(env)['students']
    domain = [('student_id', 'in', students.ids)]
    if events is not None:
        domain.append(('event_id', 'in', events.ids))
    return env['event.registration'].sudo().search(domain)


def _registration_for_family(env, registration_id):
    reg = env['event.registration'].sudo().browse(registration_id)
    if not reg.exists() or reg.student_id not in school_context(env)['students']:
        return None, api_error('Registration not found.', status=404, code='not_found')
    return reg, None


class BxiApiSupportEventController(http.Controller):

    @http.route('/api/v1/events', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_events(self, include_past=None, **kwargs):
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = _visible_domain(request.env)
        if include_past not in ('1', 'true', 'True'):
            domain = Domain.AND([domain, Domain('date_end', '>=', fields.Datetime.now())])
        Event = request.env['event.event'].sudo()
        total = Event.search_count(domain)
        events = Event.search(domain, limit=limit, offset=offset, order='date_begin')
        registrations = _family_registrations(request.env, events)
        return api_response({'events': [_event_dict(e, registrations) for e in events]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/events/<int:event_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_event(self, event_id, **kwargs):
        event = request.env['event.event'].sudo().browse(event_id)
        if not event.exists() or not event.filtered_domain(_visible_domain(request.env)):
            return api_error('Event not found.', status=404, code='not_found')
        return api_response(_event_dict(event, _family_registrations(request.env, event), detail=True))

    @http.route('/api/v1/events/<int:event_id>/register', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def register(self, event_id, **kwargs):
        """Register one of the caller's students. A paid or permission-slip
        event starts 'draft' and is confirmed via /confirm once paid and
        signed - the school module's own rule."""
        payload = request.get_json_data() or {}
        context = school_context(request.env)
        student, error = get_viewable_student(
            request.env, payload.get('student_id'), allow=lambda env, s: s in context['students'])
        if error:
            return error
        event = request.env['event.event'].sudo().browse(event_id)
        if not event.exists() or not event.filtered_domain(_visible_domain(request.env)):
            return api_error('Event not found.', status=404, code='not_found')
        if event.is_finished:
            return api_error('This event is over.', status=400, code='event_finished')
        if request.env['event.registration'].sudo().search_count([
            ('event_id', '=', event.id), ('student_id', '=', student.id), ('state', '!=', 'cancel'),
        ]):
            return api_error('This student is already registered.', status=400, code='already_registered')
        if event.seats_limited and event.seats_available <= 0:
            return api_error('This event is full.', status=400, code='event_full')
        needs_steps = event.is_paid_event or event.requires_permission_slip
        reg, error = safe_create(request.env['event.registration'].sudo(), {
            'event_id': event.id,
            'student_id': student.id,
            'parent_id': context['parent'].id or False,
            'partner_id': student.partner_id.id,
            'name': student.name,
            'email': student.email or False,
            'state': 'draft' if needs_steps else 'open',
        })
        if error:
            return error
        return api_response(_registration_dict(reg), status=201)

    @http.route('/api/v1/me/event-registrations', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def my_registrations(self, **kwargs):
        registrations = _family_registrations(request.env)
        return api_response({'registrations': [
            dict(_registration_dict(r), event=_event_dict(r.event_id)) for r in registrations
        ]})

    @http.route('/api/v1/event-registrations/<int:registration_id>/sign-permission-slip', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def sign_permission_slip(self, registration_id, **kwargs):
        reg, error = _registration_for_family(request.env, registration_id)
        if error:
            return error
        if not school_context(request.env)['parent']:
            return api_error('Only a parent can sign the permission slip.', status=403, code='forbidden')
        if not reg.event_id.requires_permission_slip:
            return api_error('This event needs no permission slip.', status=400, code='not_required')
        signed_by = (request.get_json_data() or {}).get('signed_by') or request.env.user.name
        _, error = call_action(reg, 'action_sign_permission_slip', signed_by=signed_by)
        if error:
            return error
        return api_response(_registration_dict(reg))

    @http.route('/api/v1/event-registrations/<int:registration_id>/confirm', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def confirm(self, registration_id, **kwargs):
        """Confirm a draft registration. For a paid event the first call
        raises the invoice and answers 402 payment_required; call again
        once the invoice is paid."""
        reg, error = _registration_for_family(request.env, registration_id)
        if error:
            return error
        if reg.state != 'draft':
            return api_error('This registration is not awaiting confirmation.', status=400, code='invalid_transition')
        _, error = call_action(reg, 'action_confirm')
        if error:
            if reg.event_id.is_paid_event and reg.invoice_payment_state not in ('paid', 'in_payment'):
                return api_error(
                    'Payment is required first - the invoice is on this registration in /me/event-registrations.',
                    status=402, code='payment_required')
            return error
        return api_response(_registration_dict(reg))

    @http.route('/api/v1/event-registrations/<int:registration_id>/cancel', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def cancel(self, registration_id, **kwargs):
        reg, error = _registration_for_family(request.env, registration_id)
        if error:
            return error
        if reg.state in ('done', 'cancel'):
            return api_error('This registration can no longer be cancelled.', status=400, code='invalid_transition')
        _, error = call_action(reg, 'action_cancel')
        if error:
            return error
        return api_response(_registration_dict(reg))

    @http.route('/api/v1/event-registrations/<int:registration_id>/add-transport', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def add_transport(self, registration_id, **kwargs):
        """Book the event's bus for this student: {"route_id", "stop_id"}.
        Creates a draft transport registration the transport office
        confirms, same as booking it from the backend."""
        reg, error = _registration_for_family(request.env, registration_id)
        if error:
            return error
        if not reg.event_id.requires_transport:
            return api_error('This event offers no transport.', status=400, code='not_offered')
        if reg.transport_registration_id:
            return api_error('Transport is already booked.', status=400, code='already_booked')
        payload = request.get_json_data() or {}
        route_id, error = parse_int(payload.get('route_id'), 'route_id')
        if error:
            return error
        stop_id, error = parse_int(payload.get('stop_id'), 'stop_id')
        if error:
            return error
        stop = request.env['bxi.transport.route.stop'].sudo().browse(stop_id)
        if not stop.exists() or stop.route_id.id != route_id or stop.route_id.state != 'active':
            return api_error('Stop not found on an active route.', status=404, code='not_found')
        transport, error = safe_create(request.env['bxi.transport.registration'].sudo(), {
            'student_id': reg.student_id.id,
            'route_id': route_id,
            'stop_id': stop.id,
            'date_start': fields.Datetime.to_datetime(reg.event_id.date_begin).date(),
            'date_end': fields.Datetime.to_datetime(reg.event_id.date_end).date(),
            'event_registration_id': reg.id,
        })
        if error:
            return error
        return api_response(dict(_registration_dict(reg), transport={
            'id': transport.id, 'name': transport.name, 'state': transport.state,
        }), status=201)

    @http.route('/api/v1/events/<int:event_id>/registrations', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def event_registrations(self, event_id, **kwargs):
        """Coordinator view of everyone registered for an event."""
        event = request.env['event.event'].sudo().browse(event_id)
        if not event.exists():
            return api_error('Event not found.', status=404, code='not_found')
        if not (_is_coordinator(request.env.user) or school_context(request.env)['faculty'] in event.coordinator_ids):
            return api_error('Not authorized for this event.', status=403, code='forbidden')
        return api_response({'event': _event_dict(event), 'registrations': [
            _registration_dict(r) for r in event.registration_ids
        ]})
