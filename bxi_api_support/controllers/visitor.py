# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Gate app for visitor_management: find or register a visitor, check them
in against a host employee, check them out, and see who is on campus."""
import base64
from datetime import datetime, time

from odoo import fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import (
    api_error, api_response, call_action, parse_int, parse_request, require_auth,
)

from .common import date_str, parse_pagination, ref, safe_create

GATE_GROUPS = ('visitor_management.group_visitor_officer', 'visitor_management.group_visitor_management')
VISITOR_TYPES = ('buyer', 'guest', 'supplier', 'delivery')


def _is_gate_staff(user):
    return any(user.has_group(group) for group in GATE_GROUPS)


def _visitor_dict(visitor):
    return {
        'id': visitor.id,
        'reference': visitor.visitor_seq,
        'name': visitor.v_name,
        'company': visitor.v_company,
        'phone': visitor.v_phn,
        'email': visitor.v_email or None,
        'gender': visitor.v_gender,
        'type': visitor.I_AM,
        'category': ref(visitor.category_id),
        'has_photo': bool(visitor.v_image),
    }


def _visit_dict(visit):
    return {
        'id': visit.id,
        'visitor': _visitor_dict(visit.v_name),
        'host': {'id': visit.employee_id.id, 'name': visit.employee_id.name,
                 'department': ref(visit.dept), 'phone': visit.work_phone or None},
        'purpose': visit.v_purpose or None,
        'check_in': date_str(visit.check_in_date),
        'check_out': date_str(visit.check_out_date),
        'state': visit.state,
        'visit_count': visit.entry_count,
    }


def _gate_guard():
    if not _is_gate_staff(request.env.user):
        return api_error('Only gate/visitor staff can use the visitor desk.', status=403, code='forbidden')
    return None


class BxiApiSupportVisitorController(http.Controller):

    @http.route('/api/v1/visitors', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def find_visitors(self, q=None, **kwargs):
        """Look a returning visitor up by name, phone or company."""
        error = _gate_guard()
        if error:
            return error
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = ['|', '|', ('v_name', 'ilike', q), ('v_phn', 'ilike', q), ('v_company', 'ilike', q)] if q else []
        Visitor = request.env['visitor.data'].sudo()
        total = Visitor.search_count(domain)
        visitors = Visitor.search(domain, limit=limit, offset=offset, order='id desc')
        return api_response({'visitors': [_visitor_dict(v) for v in visitors]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/visitors', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def register_visitor(self, **kwargs):
        """{name, company, phone, type, gender?, email?, address?,
        category_id?} plus an optional photo (multipart or base64)."""
        error = _gate_guard()
        if error:
            return error
        payload, files, error = parse_request()
        if error:
            return error
        for required in ('name', 'company', 'phone', 'type'):
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        if payload['type'] not in VISITOR_TYPES:
            return api_error('type must be one of %s.' % ', '.join(VISITOR_TYPES), status=400, code='invalid_type')
        vals = {
            'v_name': payload['name'], 'v_company': payload['company'], 'v_phn': payload['phone'],
            'I_AM': payload['type'], 'v_gender': payload.get('gender') or 'male',
            'v_email': payload.get('email') or False, 'v_address': payload.get('address') or False,
        }
        if payload.get('category_id'):
            vals['category_id'], error = parse_int(payload['category_id'], 'category_id')
            if error:
                return error
        if files:
            vals['v_image'] = base64.b64encode(files[0]['content'])
        visitor, error = safe_create(request.env['visitor.data'].sudo(), vals)
        if error:
            return error
        return api_response(_visitor_dict(visitor), status=201)

    @http.route('/api/v1/visits', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def check_in(self, **kwargs):
        """{visitor_id, host_employee_id, purpose?}: open a visit and check
        the visitor in."""
        error = _gate_guard()
        if error:
            return error
        payload = request.get_json_data() or {}
        visitor_id, error = parse_int(payload.get('visitor_id'), 'visitor_id')
        if error:
            return error
        host_id, error = parse_int(payload.get('host_employee_id'), 'host_employee_id')
        if error:
            return error
        visitor = request.env['visitor.data'].sudo().browse(visitor_id)
        if not visitor.exists():
            return api_error('Visitor not found.', status=404, code='not_found')
        if request.env['visit.data'].sudo().search_count([('v_name', '=', visitor.id), ('state', '=', 'checkin')]):
            return api_error('This visitor is already checked in.', status=400, code='already_checked_in')
        visit, error = safe_create(request.env['visit.data'].sudo(), {
            'v_name': visitor.id, 'employee_id': host_id, 'v_purpose': payload.get('purpose') or False,
            'check_in_date': fields.Datetime.now(),
        })
        if error:
            return error
        _, error = call_action(visit, 'check_in_action')
        if error:
            return error
        return api_response(_visit_dict(visit), status=201)

    @http.route('/api/v1/visits/<int:visit_id>/checkout', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def check_out(self, visit_id, **kwargs):
        error = _gate_guard()
        if error:
            return error
        visit = request.env['visit.data'].sudo().browse(visit_id)
        if not visit.exists():
            return api_error('Visit not found.', status=404, code='not_found')
        _, error = call_action(visit, 'check_out_action')
        if error:
            return error
        return api_response(_visit_dict(visit))

    @http.route('/api/v1/visits', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_visits(self, state=None, date=None, **kwargs):
        """Visits of one day (default today), optionally ?state=checkin for
        who is still on campus."""
        error = _gate_guard()
        if error:
            return error
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        try:
            day = fields.Date.to_date(date) if date else fields.Date.context_today(request.env.user)
        except ValueError:
            return api_error('date must be YYYY-MM-DD.', status=400, code='invalid_date')
        domain = [('check_in_date', '>=', datetime.combine(day, time.min)),
                  ('check_in_date', '<=', datetime.combine(day, time.max))]
        if state:
            domain.append(('state', '=', state))
        Visit = request.env['visit.data'].sudo()
        total = Visit.search_count(domain)
        visits = Visit.search(domain, limit=limit, offset=offset, order='check_in_date desc')
        return api_response({'visits': [_visit_dict(v) for v in visits]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/visits/today', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def today(self, **kwargs):
        """Gate dashboard: today's counts and everyone still checked in
        (whatever day they arrived)."""
        error = _gate_guard()
        if error:
            return error
        today = fields.Date.context_today(request.env.user)
        Visit = request.env['visit.data'].sudo()
        todays = Visit.search([('check_in_date', '>=', datetime.combine(today, time.min)),
                               ('check_in_date', '<=', datetime.combine(today, time.max))])
        on_campus = Visit.search([('state', '=', 'checkin')], order='check_in_date')
        return api_response({
            'date': date_str(today),
            'visits_today': len(todays),
            'checked_out_today': len(todays.filtered(lambda v: v.state == 'checkout')),
            'on_campus_count': len(on_campus),
            'on_campus': [_visit_dict(v) for v in on_campus],
        })
