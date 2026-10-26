# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth

from .common import date_str, is_staff, parse_pagination


def _subjects_of_class(env, course_id):
    return [('id', 'in', env['op.course'].sudo().browse(course_id).subject_ids.ids)]


# name -> lookup definition. Read-only reference data the app caches for
# dropdowns and to resolve the *_id values other endpoints ask for.
#   model     - Odoo model
#   fields    - fields returned for each record (many2one -> {id, name})
#   domain    - fixed domain
#   filters   - optional `?param=<id>` query filters: (param, field) or
#               (param, callable(env, id) -> domain)
#   staff     - True: staff logins only (internal setup, not family data)
#   order     - search order
MASTERS = {
    'academic-years': {'model': 'op.academic.year', 'fields': ['name', 'start_date', 'end_date'],
                       'order': 'start_date desc'},
    'academic-terms': {'model': 'op.academic.term', 'fields': ['name', 'term_start_date', 'term_end_date', 'academic_year_id'],
                       'filters': [('academic_year_id', 'academic_year_id')], 'order': 'term_start_date desc'},
    'classes': {'model': 'op.course', 'fields': ['name', 'code', 'department_id'], 'order': 'name'},
    'sections': {'model': 'op.batch', 'fields': ['name', 'code', 'course_id', 'start_date', 'end_date'],
                 'filters': [('course_id', 'course_id')], 'order': 'name'},
    'subjects': {'model': 'op.subject', 'fields': ['name', 'code', 'type', 'subject_type', 'department_id'],
                 'filters': [('course_id', _subjects_of_class)], 'order': 'name'},
    'timings': {'model': 'op.timing', 'fields': ['name', 'display_label', 'start_time', 'end_time', 'is_break'],
                'order': 'sequence, start_time'},
    'classrooms': {'model': 'op.classroom', 'fields': ['name', 'code', 'capacity', 'course_id', 'batch_id'], 'order': 'name'},
    'departments': {'model': 'op.department', 'fields': ['name', 'code'], 'order': 'name'},
    'relationships': {'model': 'op.parent.relationship', 'fields': ['name'], 'order': 'name'},
    'exam-types': {'model': 'op.exam.type', 'fields': ['name', 'code'], 'order': 'name'},
    'assignment-types': {'model': 'grading.assignment.type', 'fields': ['name', 'code', 'assign_type'], 'order': 'name'},
    'library-genres': {'model': 'op.media.genre', 'fields': ['name'], 'order': 'name'},
    'activity-types': {'model': 'op.activity.type', 'fields': ['name'], 'order': 'name'},
    'certificate-types': {'model': 'op.certificate.type', 'fields': ['name', 'code', 'category', 'requires_approval'],
                          'order': 'name'},
    'scholarship-programs': {'model': 'bxi.scholarship.program',
                             'fields': ['name', 'scholarship_type', 'default_coverage_type', 'default_coverage_percentage'],
                             'order': 'name'},
    'vaccine-types': {'model': 'op.health.vaccine.type', 'fields': ['name', 'code', 'doses_required'], 'order': 'name'},
    'lab-rooms': {'model': 'lab.room', 'fields': ['name', 'code', 'lab_type', 'capacity', 'instructor_id'], 'order': 'name'},
    'lab-equipment': {'model': 'lab.equipment', 'fields': ['name', 'code', 'lab_id', 'quantity_available', 'condition'],
                      'filters': [('lab_id', 'lab_id')], 'order': 'name'},
    'lab-experiments': {'model': 'lab.experiment', 'fields': ['name', 'code', 'subject_id', 'max_marks'],
                        'filters': [('subject_id', 'subject_id')], 'order': 'name'},
    'canteen-menu': {'model': 'product.product', 'fields': ['name', 'list_price', 'veg_type', 'categ_id'],
                     'domain': [('is_canteen_item', '=', True), ('available_today', '=', True), ('sale_ok', '=', True)],
                     'order': 'name'},
    'uniform-policies': {'model': 'bxi.uniform.policy', 'fields': ['display_name', 'course_id', 'gender', 'season'],
                         'filters': [('course_id', 'course_id')], 'order': 'id'},
    'transport-stops': {'model': 'bxi.transport.route.stop',
                        'fields': ['name', 'route_id', 'sequence', 'pickup_time', 'drop_time', 'fee_amount'],
                        'domain': [('route_id.state', '=', 'active')],
                        'filters': [('route_id', 'route_id')], 'order': 'route_id, sequence'},
    'event-venues': {'model': 'bxi.event.venue', 'fields': ['name', 'code', 'building', 'capacity'], 'order': 'name'},
    'visitor-categories': {'model': 'visitor.category', 'fields': ['name'], 'order': 'name', 'staff': True},
    'visit-hosts': {'model': 'hr.employee', 'fields': ['name', 'department_id', 'job_title', 'work_phone'],
                    'domain': [('employee_type', '!=', 'student')], 'order': 'name', 'staff': True},
    'payment-journals': {'model': 'account.journal', 'fields': ['name', 'code', 'type'],
                         'domain': [('type', 'in', ('bank', 'cash'))], 'order': 'name', 'staff': True},
    'countries': {'model': 'res.country', 'fields': ['name', 'code'], 'order': 'name'},
    'country-states': {'model': 'res.country.state', 'fields': ['name', 'code', 'country_id'],
                       'filters': [('country_id', 'country_id')], 'order': 'name'},
}


def _serialize_value(record, field_name):
    field = record._fields[field_name]
    value = record[field_name]
    if field.type == 'many2one':
        return {'id': value.id, 'name': value.display_name} if value else None
    if field.type in ('many2many', 'one2many'):
        return value.ids
    if field.type in ('date', 'datetime'):
        return date_str(value)
    if field.type in ('char', 'text', 'selection', 'html') and value is False:
        return None
    return value


def serialize_record(record, field_names):
    data = {'id': record.id}
    for field_name in field_names:
        data[field_name] = _serialize_value(record, field_name)
    return data


class BxiApiSupportMastersController(http.Controller):

    @http.route('/api/v1/masters', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_masters(self, **kwargs):
        staff = is_staff(request.env)
        return api_response({'masters': sorted(
            name for name, spec in MASTERS.items()
            if spec['model'] in request.env and (staff or not spec.get('staff'))
        )})

    @http.route('/api/v1/masters/<string:name>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_master(self, name, **kwargs):
        spec = MASTERS.get(name)
        if not spec or spec['model'] not in request.env:
            return api_error(f"Unknown master '{name}'.", status=404, code='not_found')
        if spec.get('staff') and not is_staff(request.env):
            return api_error('Not authorized for this list.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs, default_limit=200, max_limit=1000)
        if error:
            return error
        domain = list(spec.get('domain', []))
        for param, field in spec.get('filters', []):
            if kwargs.get(param):
                value, error = parse_int(kwargs[param], param)
                if error:
                    return error
                domain += field(request.env, value) if callable(field) else [(field, '=', value)]
        if kwargs.get('q'):
            rec_name = request.env[spec['model']]._rec_name or 'name'
            domain.append((rec_name, 'ilike', kwargs['q']))
        Model = request.env[spec['model']].sudo()
        total = Model.search_count(domain)
        records = Model.search(domain, limit=limit, offset=offset, order=spec.get('order'))
        return api_response(
            {'items': [serialize_record(r, spec['fields']) for r in records]},
            meta={'total': total, 'limit': limit, 'offset': offset})
