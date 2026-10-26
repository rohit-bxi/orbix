# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import get_authorized_student, get_own_student_ids, get_viewable_student, parse_pagination, safe_create

STAFF_GROUP = 'bxi_school_transport_bus_management.group_transport_staff'
MANAGER_GROUP = 'bxi_school_transport_bus_management.group_transport_manager'


def _is_transport_staff(user):
    return user.has_group(STAFF_GROUP) or user.has_group(MANAGER_GROUP)


def _route_dict(route):
    return {
        'id': route.id,
        'name': route.name,
        'code': route.code,
        'vehicle': route.vehicle_id.display_name,
        'distance_km': route.distance_km,
        'fee_amount': route.fee_amount,
        'seats_available': route.seats_available,
        'state': route.state,
        'stops': [{
            'id': s.id, 'name': s.name, 'sequence': s.sequence,
            'pickup_time': s.pickup_time, 'drop_time': s.drop_time, 'fee_amount': s.fee_amount,
        } for s in route.stop_ids],
    }


def _registration_dict(reg):
    return {
        'id': reg.id,
        'name': reg.name,
        'student_id': reg.student_id.id,
        'route_id': reg.route_id.id,
        'stop_id': reg.stop_id.id,
        'date_start': reg.date_start and reg.date_start.isoformat(),
        'date_end': reg.date_end and reg.date_end.isoformat(),
        'fee_amount': reg.fee_amount,
        'state': reg.state,
        'invoice_payment_state': reg.invoice_payment_state,
    }


class BxiApiSupportTransportController(http.Controller):

    @http.route('/api/v1/transport/routes', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_routes(self, **kwargs):
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [] if _is_transport_staff(request.env.user) else [('state', '=', 'active')]
        Route = request.env['bxi.transport.route'].sudo()
        total = Route.search_count(domain)
        routes = Route.search(domain, limit=limit, offset=offset)
        return api_response(
            {'routes': [_route_dict(r) for r in routes]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/transport/routes/<int:route_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_route(self, route_id, **kwargs):
        route = request.env['bxi.transport.route'].sudo().browse(route_id)
        if not route.exists():
            return api_error('Route not found.', status=404, code='not_found')
        if route.state != 'active' and not _is_transport_staff(request.env.user):
            return api_error('Not authorized for this route.', status=403, code='forbidden')
        return api_response(_route_dict(route))

    @http.route('/api/v1/transport/routes/<int:route_id>/activate', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def activate_route(self, route_id, **kwargs):
        return self._route_transition(route_id, 'action_activate')

    @http.route('/api/v1/transport/routes/<int:route_id>/archive', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def archive_route(self, route_id, **kwargs):
        return self._route_transition(route_id, 'action_archive_route')

    @http.route('/api/v1/transport/routes/<int:route_id>/set-draft', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def set_draft_route(self, route_id, **kwargs):
        return self._route_transition(route_id, 'action_set_draft')

    def _route_transition(self, route_id, method_name):
        if not _is_transport_staff(request.env.user):
            return api_error('Not authorized to manage routes.', status=403, code='forbidden')
        route = request.env['bxi.transport.route'].sudo().browse(route_id)
        if not route.exists():
            return api_error('Route not found.', status=404, code='not_found')
        _, error = call_action(route, method_name)
        if error:
            return error
        return api_response(_route_dict(route))

    @http.route('/api/v1/transport/registrations', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_registrations(self, **kwargs):
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [] if _is_transport_staff(request.env.user) else [
            ('student_id', 'in', get_own_student_ids(request.env))]
        Registration = request.env['bxi.transport.registration'].sudo()
        total = Registration.search_count(domain)
        registrations = Registration.search(domain, limit=limit, offset=offset, order='id desc')
        return api_response(
            {'registrations': [_registration_dict(r) for r in registrations]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/transport/registrations/<int:registration_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_registration(self, registration_id, **kwargs):
        registration, error = self._authorized_registration(registration_id)
        if error:
            return error
        return api_response(_registration_dict(registration))

    @http.route('/api/v1/transport/registrations', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_registration(self, **kwargs):
        payload = request.get_json_data() or {}
        student, error = get_authorized_student(payload.get('student_id'), is_staff=_is_transport_staff)
        if error:
            return error
        if not payload.get('route_id'):
            return api_error('route_id is required.', status=400, code='missing_route_id')
        if not payload.get('stop_id'):
            return api_error('stop_id is required.', status=400, code='missing_stop_id')

        vals = {'student_id': student.id, 'route_id': payload['route_id'], 'stop_id': payload['stop_id']}
        if payload.get('date_start'):
            vals['date_start'] = payload['date_start']
        registration, error = safe_create(request.env['bxi.transport.registration'].sudo(), vals)
        if error:
            return error
        return api_response(_registration_dict(registration), status=201)

    @http.route('/api/v1/transport/registrations/<int:registration_id>/confirm', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def confirm_registration(self, registration_id, **kwargs):
        return self._transition(registration_id, 'action_confirm', require_owner=True)

    @http.route('/api/v1/transport/registrations/<int:registration_id>/activate', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def activate_registration(self, registration_id, **kwargs):
        return self._transition(registration_id, 'action_activate')

    @http.route('/api/v1/transport/registrations/<int:registration_id>/cancel', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def cancel_registration(self, registration_id, **kwargs):
        return self._transition(registration_id, 'action_cancel', require_owner=True)

    @http.route('/api/v1/transport/registrations/<int:registration_id>/set-draft', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def set_draft_registration(self, registration_id, **kwargs):
        return self._transition(registration_id, 'action_set_draft')

    def _transition(self, registration_id, method_name, require_owner=False):
        registration = request.env['bxi.transport.registration'].sudo().browse(registration_id)
        if not registration.exists():
            return api_error('Registration not found.', status=404, code='not_found')
        if require_owner:
            if not _is_transport_staff(request.env.user) \
                    and registration.student_id.id not in get_own_student_ids(request.env):
                return api_error('Not authorized for this registration.', status=403, code='forbidden')
        elif not _is_transport_staff(request.env.user):
            return api_error('Not authorized for this action.', status=403, code='forbidden')
        _, error = call_action(registration, method_name)
        if error:
            return error
        return api_response(_registration_dict(registration))

    def _authorized_registration(self, registration_id):
        registration = request.env['bxi.transport.registration'].sudo().browse(registration_id)
        if not registration.exists():
            return None, api_error('Registration not found.', status=404, code='not_found')
        if _is_transport_staff(request.env.user) \
                or registration.student_id.id in get_own_student_ids(request.env):
            return registration, None
        return None, api_error('Not authorized for this registration.', status=403, code='forbidden')

    @http.route('/api/v1/transport/bulk-register', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def bulk_register(self, **kwargs):
        if not _is_transport_staff(request.env.user):
            return api_error('Not authorized to bulk-register students.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        for field in ('batch_id', 'route_id', 'stop_id'):
            if not payload.get(field):
                return api_error('%s is required.' % field, status=400, code='missing_%s' % field)
        vals = {key: payload[key] for key in ('batch_id', 'route_id', 'stop_id', 'date_start') if key in payload}
        wizard, error = safe_create(request.env['bxi.transport.bulk.registration.wizard'].sudo(), vals)
        if error:
            return error
        _, error = call_action(wizard, 'action_register')
        if error:
            return error
        registrations = request.env['bxi.transport.registration'].sudo().search(
            [('route_id', '=', payload['route_id']), ('stop_id', '=', payload['stop_id'])], order='id desc')
        return api_response({'registrations': [_registration_dict(r) for r in registrations]}, status=201)

    @http.route('/api/v1/transport/my', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def my_transport(self, student_id=None, **kwargs):
        """The family's bus card: the student's current registrations with
        route, stop, pickup/drop times, bus and the crew to call."""
        student, error = get_viewable_student(request.env, student_id)
        if error:
            return error
        registrations = request.env['bxi.transport.registration'].sudo().search([
            ('student_id', '=', student.id), ('state', 'in', ('confirmed', 'active')),
        ], order='date_start desc')
        result = []
        for reg in registrations:
            route = reg.route_id
            driver = route.vehicle_id.transport_driver_id
            result.append(dict(
                _registration_dict(reg),
                route={'id': route.id, 'name': route.name, 'code': route.code or None},
                stop={'id': reg.stop_id.id, 'name': reg.stop_id.name,
                      'pickup_time': reg.pickup_time, 'drop_time': reg.drop_time},
                vehicle={'id': route.vehicle_id.id, 'name': route.vehicle_id.display_name,
                         'license_plate': route.vehicle_id.license_plate or None} if route.vehicle_id else None,
                driver={'name': driver.name, 'phone': driver.phone or None} if driver else None,
                attendant={'name': route.attendant_id.name, 'phone': route.attendant_id.phone or None}
                if route.attendant_id else None,
            ))
        return api_response({'registrations': result})

    # -- route set-up (transport office) -----------------------------------------

    STOP_FIELDS = ('name', 'sequence', 'pickup_time', 'drop_time', 'fee_amount')

    @http.route('/api/v1/transport/routes/<int:route_id>/stops', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def add_stop(self, route_id, **kwargs):
        if not _is_transport_staff(request.env.user):
            return api_error('Not authorized to edit routes.', status=403, code='forbidden')
        route = request.env['bxi.transport.route'].sudo().browse(route_id)
        if not route.exists():
            return api_error('Route not found.', status=404, code='not_found')
        payload = request.get_json_data() or {}
        if not payload.get('name'):
            return api_error('name is required.', status=400, code='missing_name')
        _stop, error = safe_create(request.env['bxi.transport.route.stop'].sudo(), dict(
            {k: payload[k] for k in self.STOP_FIELDS if k in payload}, route_id=route.id))
        if error:
            return error
        return api_response(_route_dict(route), status=201)

    @http.route('/api/v1/transport/stops/<int:stop_id>/<any("update", "delete"):action>',
                type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def change_stop(self, stop_id, action, **kwargs):
        if not _is_transport_staff(request.env.user):
            return api_error('Not authorized to edit routes.', status=403, code='forbidden')
        stop = request.env['bxi.transport.route.stop'].sudo().browse(stop_id)
        if not stop.exists():
            return api_error('Stop not found.', status=404, code='not_found')
        route = stop.route_id
        if action == 'delete':
            if stop.registration_ids.filtered(lambda r: r.state in ('confirmed', 'active')):
                return api_error('Students are registered at this stop.', status=400, code='stop_in_use')
            stop.unlink()
        else:
            payload = request.get_json_data() or {}
            _, error = call_action(stop, 'write', vals={k: payload[k] for k in self.STOP_FIELDS if k in payload})
            if error:
                return error
        return api_response(_route_dict(route))

    @http.route('/api/v1/transport/vehicles', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_vehicles(self, **kwargs):
        if not _is_transport_staff(request.env.user):
            return api_error('Not authorized to view vehicles.', status=403, code='forbidden')
        vehicles = request.env['fleet.vehicle'].sudo().search([('is_school_bus', '=', True)])
        return api_response({'vehicles': [{
            'id': v.id,
            'name': v.display_name,
            'license_plate': v.license_plate or None,
            'seats': v.seats,
            'driver': {'id': v.transport_driver_id.id, 'name': v.transport_driver_id.name,
                       'phone': v.transport_driver_id.phone or None} if v.transport_driver_id else None,
            'attendant': {'name': v.bus_attendant_id.name, 'phone': v.bus_attendant_id.phone or None}
            if v.bus_attendant_id else None,
        } for v in vehicles]})

    @http.route('/api/v1/transport/drivers', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_drivers(self, **kwargs):
        if not _is_transport_staff(request.env.user):
            return api_error('Not authorized to view drivers.', status=403, code='forbidden')
        drivers = request.env['bxi.transport.driver'].sudo().search([])
        return api_response({'drivers': [{
            'id': d.id,
            'name': d.name,
            'phone': d.phone or None,
            'license_number': d.license_number,
            'license_expiry': d.license_expiry and d.license_expiry.isoformat(),
            'license_expiring_soon': d.license_expiring_soon,
            'badge_verified': d.badge_verified,
            'status': d.status,
            'vehicle_id': d.vehicle_id.id or None,
        } for d in drivers]})
