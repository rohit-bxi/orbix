# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Transport set-up (bxi_school_transport_bus_management) for the
transport office: creating and editing bus routes (with their stops),
school buses (fleet.vehicle) and driver profiles. Reading them, route
activation and per-stop edits stay in transport.py."""
from odoo import Command, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth

from .common import atomic, check_selection, date_str, parse_date, resolve_record
from .transport import _is_transport_staff, _route_dict

STOP_FIELDS = ('name', 'sequence', 'pickup_time', 'drop_time', 'fee_amount')


def _forbidden():
    return api_error('Only transport staff can set up transport.', status=403, code='forbidden')


def _number(payload, key, minimum=0):
    try:
        value = float(payload[key] or 0)
    except (TypeError, ValueError):
        return None, api_error(f'{key} must be a number.', status=400, code=f'invalid_{key}')
    if value < minimum:
        return None, api_error(f'{key} cannot be below {minimum:g}.', status=400, code=f'invalid_{key}')
    return value, None


def _route_vals(env, payload, route=None):
    vals = {}
    if 'name' in payload:
        if not payload['name']:
            return None, api_error('name cannot be empty.', status=400, code='missing_name')
        vals['name'] = payload['name']
    if 'code' in payload:
        code = payload['code'] or False
        if code and env['bxi.transport.route'].sudo().with_context(active_test=False).search_count(
                [('code', '=', code), ('company_id', '=', env.company.id)]
                + ([('id', '!=', route.id)] if route else [])):
            return None, api_error(f"Route code '{code}' is already used.", status=400, code='duplicate_code')
        vals['code'] = code
    if 'vehicle_id' in payload:
        vehicle, error = resolve_record(env, 'fleet.vehicle', payload['vehicle_id'], 'vehicle_id')
        if error:
            return None, error
        if not vehicle:
            return None, api_error('vehicle_id is required.', status=400, code='missing_vehicle_id')
        if not vehicle.is_school_bus:
            return None, api_error('This vehicle is not marked as a school bus.', status=400, code='not_school_bus')
        vals['vehicle_id'] = vehicle.id
    for key, model in (('academic_year_id', 'op.academic.year'), ('fee_product_id', 'product.product')):
        if key in payload:
            record, error = resolve_record(env, model, payload[key], key)
            if error:
                return None, error
            if key == 'fee_product_id' and not record:
                continue
            vals[key] = record.id or False
    for key in ('distance_km', 'fee_amount'):
        if key in payload:
            vals[key], error = _number(payload, key)
            if error:
                return None, error
    return vals, None


def _stop_lines(stops):
    if not isinstance(stops, list):
        return None, api_error('stops must be a list.', status=400, code='invalid_stops')
    lines = []
    for index, stop in enumerate(stops):
        if not isinstance(stop, dict) or not stop.get('name'):
            return None, api_error(f'stops[{index}].name is required.', status=400, code='missing_stop_name')
        vals = {k: stop[k] for k in STOP_FIELDS if k in stop}
        vals.setdefault('sequence', (index + 1) * 10)
        lines.append(Command.create(vals))
    return lines, None


def _vehicle_dict(vehicle):
    driver = vehicle.transport_driver_id
    return {
        'id': vehicle.id,
        'name': vehicle.display_name,
        'model': ref_model(vehicle.model_id),
        'license_plate': vehicle.license_plate or None,
        'seats': vehicle.seats,
        'academic_year': {'id': vehicle.academic_year_id.id, 'name': vehicle.academic_year_id.name}
        if vehicle.academic_year_id else None,
        'driver': {'id': driver.id, 'name': driver.name, 'phone': driver.phone or None} if driver else None,
        'attendant': {'name': vehicle.bus_attendant_id.name, 'phone': vehicle.bus_attendant_id.phone or None}
        if vehicle.bus_attendant_id else None,
        'routes': [{'id': r.id, 'name': r.name, 'state': r.state} for r in vehicle.route_ids],
        'active': vehicle.active,
    }


def ref_model(model):
    return {'id': model.id, 'name': model.display_name} if model else None


def _driver_dict(driver):
    return {
        'id': driver.id,
        'name': driver.name,
        'phone': driver.phone or None,
        'email': driver.partner_id.email or None,
        'employee_id': driver.employee_id.id or None,
        'license_number': driver.license_number,
        'license_type': driver.license_type,
        'license_expiry': date_str(driver.license_expiry),
        'license_expiring_soon': driver.license_expiring_soon,
        'badge_verified': driver.badge_verified,
        'status': driver.status,
        'vehicle_id': driver.vehicle_id.id or None,
        'active': driver.active,
    }


class BxiApiSupportTransportAdminController(http.Controller):

    def _get(self, model, record_id, label):
        record = request.env[model].sudo().with_context(active_test=False).browse(record_id)
        if not record.exists():
            return None, api_error(f'{label} not found.', status=404, code='not_found')
        return record, None

    # -- routes ------------------------------------------------------------------

    @http.route('/api/v1/transport/routes', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_route(self, **kwargs):
        """{"name", "vehicle_id", "code"?, "academic_year_id"?,
        "distance_km"?, "fee_amount"?, "fee_product_id"?, "stops"?: [{"name",
        "sequence"?, "pickup_time"?, "drop_time"?, "fee_amount"?}]} - a draft
        route; activate it with /transport/routes/<id>/activate."""
        env = request.env
        if not _is_transport_staff(env.user):
            return _forbidden()
        payload = request.get_json_data() or {}
        for key in ('name', 'vehicle_id'):
            if not payload.get(key):
                return api_error(f'{key} is required.', status=400, code=f'missing_{key}')
        vals, error = _route_vals(env, payload)
        if error:
            return error
        if payload.get('stops'):
            vals['stop_ids'], error = _stop_lines(payload['stops'])
            if error:
                return error
        if not vals.get('fee_product_id') and not env.ref(
                'bxi_school_transport_bus_management.product_transport_fee', raise_if_not_found=False):
            return api_error('fee_product_id is required.', status=400, code='missing_fee_product_id')
        route, error = atomic(lambda: env['bxi.transport.route'].sudo().create(vals))
        if error:
            return error
        return api_response(_route_dict(route), status=201)

    @http.route('/api/v1/transport/routes/<int:route_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_route(self, route_id, **kwargs):
        """Any create field except stops (use the stop routes). An archived
        route can't be edited; move it back to draft first."""
        env = request.env
        if not _is_transport_staff(env.user):
            return _forbidden()
        route, error = self._get('bxi.transport.route', route_id, 'Route')
        if error:
            return error
        if route.state == 'archived':
            return api_error('An archived route cannot be edited.', status=400, code='invalid_state')
        payload = request.get_json_data() or {}
        vals, error = _route_vals(env, payload, route)
        if error:
            return error
        if 'vehicle_id' in vals:
            seats = env['fleet.vehicle'].sudo().browse(vals['vehicle_id']).seats
            riders = len(route.registration_ids.filtered(lambda r: r.state in ('confirmed', 'active')))
            if seats and riders > seats:
                return api_error(f'That bus seats {seats} but {riders} students ride this route.', status=400,
                                 code='not_enough_seats')
        _, error = atomic(lambda: route.write(vals))
        if error:
            return error
        return api_response(_route_dict(route))

    # -- vehicles ----------------------------------------------------------------

    def _vehicle_vals(self, env, payload, vehicle=None):
        vals = {}
        if 'model_id' in payload:
            model, error = resolve_record(env, 'fleet.vehicle.model', payload['model_id'], 'model_id')
            if error:
                return None, error
            if not model:
                return None, api_error('model_id is required.', status=400, code='missing_model_id')
            vals['model_id'] = model.id
        if 'license_plate' in payload:
            plate = str(payload['license_plate'] or '').strip()
            if not plate:
                return None, api_error('license_plate cannot be empty.', status=400, code='missing_license_plate')
            if env['fleet.vehicle'].sudo().with_context(active_test=False).search_count(
                    [('license_plate', '=ilike', plate)] + ([('id', '!=', vehicle.id)] if vehicle else [])):
                return None, api_error(f'A vehicle with plate {plate} already exists.', status=400,
                                       code='duplicate_license_plate')
            vals['license_plate'] = plate
        if 'seats' in payload:
            seats, error = _number(payload, 'seats', minimum=1)
            if error:
                return None, error
            vals['seats'] = int(seats)
        if 'driver_id' in payload:
            driver, error = resolve_record(env, 'bxi.transport.driver', payload['driver_id'], 'driver_id')
            if error:
                return None, error
            vals['driver_id'] = driver.partner_id.id or False
        if 'academic_year_id' in payload:
            year, error = resolve_record(env, 'op.academic.year', payload['academic_year_id'], 'academic_year_id')
            if error:
                return None, error
            vals['academic_year_id'] = year.id or False
        if 'attendant' in payload:
            attendant = payload['attendant']
            if not attendant:
                vals['bus_attendant_id'] = False
            elif not isinstance(attendant, dict) or not attendant.get('name'):
                return None, api_error('attendant.name is required.', status=400, code='missing_attendant_name')
            else:
                partner = vehicle.bus_attendant_id if vehicle and vehicle.bus_attendant_id else env['res.partner']
                partner_vals = {'name': attendant['name'], 'phone': attendant.get('phone') or False}
                if partner:
                    partner.sudo().write(partner_vals)
                else:
                    partner = env['res.partner'].sudo().create(partner_vals)
                vals['bus_attendant_id'] = partner.id
        if 'active' in payload:
            vals['active'] = bool(payload['active'])
        return vals, None

    @http.route('/api/v1/transport/vehicles', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_vehicle(self, **kwargs):
        """{"model_id", "license_plate", "seats", "driver_id"? (a driver
        profile), "attendant"?: {"name", "phone"?}, "academic_year_id"?} -
        a school bus. Vehicle models come from /masters/vehicle-models."""
        env = request.env
        if not _is_transport_staff(env.user):
            return _forbidden()
        payload = request.get_json_data() or {}
        for key in ('model_id', 'license_plate', 'seats'):
            if not payload.get(key):
                return api_error(f'{key} is required.', status=400, code=f'missing_{key}')

        def create():
            vals, problem = self._vehicle_vals(env, payload)
            if problem:
                raise _PayloadError(problem)
            return env['fleet.vehicle'].sudo().create(dict(vals, is_school_bus=True))

        try:
            vehicle, error = atomic(create)
        except _PayloadError as exc:
            return exc.response
        if error:
            return error
        return api_response(_vehicle_dict(vehicle), status=201)

    @http.route('/api/v1/transport/vehicles/<int:vehicle_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_vehicle(self, vehicle_id, **kwargs):
        env = request.env
        if not _is_transport_staff(env.user):
            return _forbidden()
        vehicle, error = self._get('fleet.vehicle', vehicle_id, 'Vehicle')
        if error:
            return error
        if not vehicle.is_school_bus:
            return api_error('Vehicle not found.', status=404, code='not_found')
        payload = request.get_json_data() or {}

        def update():
            vals, problem = self._vehicle_vals(env, payload, vehicle)
            if problem:
                raise _PayloadError(problem)
            if 'seats' in vals:
                riders = len(vehicle.route_ids.registration_ids.filtered(lambda r: r.state in ('confirmed', 'active')))
                if riders > vals['seats']:
                    raise _PayloadError(api_error(f'{riders} students ride this bus; seats cannot be fewer.',
                                                  status=400, code='not_enough_seats'))
            vehicle.write(vals)

        try:
            _, error = atomic(update)
        except _PayloadError as exc:
            return exc.response
        if error:
            return error
        return api_response(_vehicle_dict(vehicle))

    # -- drivers -----------------------------------------------------------------

    def _driver_vals(self, env, payload, driver=None):
        vals = {}
        if 'license_number' in payload:
            if not payload['license_number']:
                return None, api_error('license_number cannot be empty.', status=400, code='missing_license_number')
            vals['license_number'] = payload['license_number']
        for key in ('license_type', 'status'):
            if key in payload:
                error = check_selection(env['bxi.transport.driver'], key, payload[key])
                if error:
                    return None, error
                vals[key] = payload[key]
        if 'license_expiry' in payload:
            vals['license_expiry'], error = parse_date(payload['license_expiry'], 'license_expiry')
            if error or not vals['license_expiry']:
                return None, error or api_error('license_expiry is required.', status=400,
                                                code='missing_license_expiry')
        if 'badge_verified' in payload:
            vals['badge_verified'] = bool(payload['badge_verified'])
        if 'employee_id' in payload:
            employee, error = resolve_record(env, 'hr.employee', payload['employee_id'], 'employee_id')
            if error:
                return None, error
            vals['employee_id'] = employee.id or False
        if 'active' in payload:
            vals['active'] = bool(payload['active'])
        contact = {k: payload[k] or False for k in ('name', 'phone', 'email') if k in payload}
        if 'name' in contact and not contact['name']:
            return None, api_error('name cannot be empty.', status=400, code='missing_name')
        return (vals, contact), None

    @http.route('/api/v1/transport/drivers', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_driver(self, **kwargs):
        """{"name", "phone"?, "email"?, "license_number", "license_type":
        lmv|hmv|psv, "license_expiry", "badge_verified"?, "status"?,
        "employee_id"?} - the driver's contact is created with the profile."""
        env = request.env
        if not _is_transport_staff(env.user):
            return _forbidden()
        payload = request.get_json_data() or {}
        for key in ('name', 'license_number', 'license_type', 'license_expiry'):
            if not payload.get(key):
                return api_error(f'{key} is required.', status=400, code=f'missing_{key}')
        result, error = self._driver_vals(env, payload)
        if error:
            return error
        vals, contact = result

        def create():
            partner = env['res.partner'].sudo().create(contact)
            return env['bxi.transport.driver'].sudo().create(dict(vals, partner_id=partner.id))

        driver, error = atomic(create)
        if error:
            return error
        return api_response(_driver_dict(driver), status=201)

    @http.route('/api/v1/transport/drivers/<int:driver_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_driver(self, driver_id, **kwargs):
        env = request.env
        if not _is_transport_staff(env.user):
            return _forbidden()
        driver, error = self._get('bxi.transport.driver', driver_id, 'Driver')
        if error:
            return error
        result, error = self._driver_vals(env, request.get_json_data() or {}, driver)
        if error:
            return error
        vals, contact = result

        def update():
            if contact:
                driver.partner_id.sudo().write(contact)
            driver.write(vals)

        _, error = atomic(update)
        if error:
            return error
        return api_response(_driver_dict(driver))


class _PayloadError(Exception):
    """Carries an api_error out of an atomic() block (rolling back a
    contact created for it)."""

    def __init__(self, response):
        super().__init__('invalid payload')
        self.response = response
