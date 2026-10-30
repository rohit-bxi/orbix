# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Admin dashboard - classes: every class (op.course) with its sections
(op.batch), strength and capacity; a class's detail with subject teachers;
a section's roster; and adding/editing classes and sections."""
from odoo import http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth

from ..models.res_users import COORDINATOR_GROUPS
from .common import (
    atomic, check_selection, date_str, parse_date, parse_pagination, parse_sort, ref, resolve_record,
    resolve_records,
)
from .dashboard import _allowed
from .people import MANAGER_GROUPS

VIEW_GROUPS = COORDINATOR_GROUPS + ('openeducat_core.group_op_back_office_admin',)
# Adding and editing classes is the office's job, same as people records.
EDIT_GROUPS = MANAGER_GROUPS
SORTS = {'name': 'name', 'code': 'code', 'department': 'department_id'}


def _forbidden():
    return api_error('Not authorized for class management.', status=403, code='forbidden')


def _active_domain(value):
    """?active=1 (default) active only, 0 archived only, all both."""
    if value == 'all':
        return Domain.TRUE
    return Domain('active', '=', value not in ('0', 'false'))


def _year_domain(year):
    """Sections whose dates overlap the academic year."""
    return Domain('start_date', '<=', year.end_date) & Domain('end_date', '>=', year.start_date)


def _strength(env, field, ids):
    """{course/section id: students currently enrolled}."""
    rows = env['op.student.course'].sudo()._read_group(
        [(field, 'in', ids), ('state', '=', 'running')], [field], ['__count'])
    return {record.id: count for record, count in rows}


def _fill(count, capacity):
    return round(100.0 * count / capacity, 1) if capacity else None


def _section_dict(batch, strength):
    count = strength.get(batch.id, 0)
    return {
        'id': batch.id,
        'name': batch.name,
        'code': batch.code,
        'class': ref(batch.course_id),
        'class_teacher': ref(batch.class_teacher_id),
        'capacity': batch.capacity,
        'student_count': count,
        'fill_percentage': _fill(count, batch.capacity),
        'start_date': date_str(batch.start_date),
        'end_date': date_str(batch.end_date),
        'description': batch.description or None,
        'active': batch.active,
    }


def _class_dict(course, sections, by_course, by_batch, expand=False):
    count = by_course.get(course.id, 0)
    capacity = sum(sections.mapped('capacity'))
    data = {
        'id': course.id,
        'name': course.name,
        'code': course.code,
        'department': ref(course.department_id),
        'program': ref(course.program_id),
        'parent': ref(course.parent_id),
        'evaluation_type': course.evaluation_type,
        'active': course.active,
        'section_count': len(sections),
        'student_count': count,
        'capacity': capacity,
        'fill_percentage': _fill(count, capacity),
        'subject_count': len(course.subject_ids),
        'sections_without_class_teacher': len(sections.filtered(lambda b: not b.class_teacher_id)),
    }
    if expand:
        data['sections'] = [_section_dict(b, by_batch) for b in sections]
    return data


def _check_code(env, model, code, record=None):
    """Codes are unique per model (archived records included)."""
    domain = [('code', '=', code)] + ([('id', '!=', record.id)] if record else [])
    if env[model].sudo().with_context(active_test=False).search_count(domain):
        return api_error(f"Code '{code}' is already used.", status=400, code='duplicate_code')
    return None


def _class_vals(env, payload, course=None):
    """(vals, error) for an op.course create/write."""
    vals = {}
    for key in ('name', 'code'):
        if key in payload:
            if not payload[key]:
                return None, api_error(f'{key} cannot be empty.', status=400, code=f'missing_{key}')
            vals[key] = payload[key]
    if 'evaluation_type' in payload:
        error = check_selection(env['op.course'], 'evaluation_type', payload['evaluation_type'])
        if error:
            return None, error
        vals['evaluation_type'] = payload['evaluation_type']
    for key, model in (('department_id', 'op.department'), ('program_id', 'op.program'), ('parent_id', 'op.course')):
        if key in payload:
            record, error = resolve_record(env, model, payload[key], key)
            if error:
                return None, error
            vals[key] = record.id or False
    if 'subject_ids' in payload:
        subjects, error = resolve_records(env, 'op.subject', payload['subject_ids'], 'subject_ids')
        if error:
            return None, error
        vals['subject_ids'] = [(6, 0, subjects.ids)]
    if 'active' in payload:
        vals['active'] = bool(payload['active'])
    if vals.get('code'):
        error = _check_code(env, 'op.course', vals['code'], course)
        if error:
            return None, error
    return vals, None


def _section_vals(env, payload, batch=None):
    """(vals, error) for an op.batch create/write. A missing code is
    generated from the class code and section name, missing dates default
    to the current academic year (both done by the model)."""
    vals = {}
    for key in ('name', 'code'):
        if key in payload:
            if not payload[key]:
                if key == 'code' and not batch:
                    continue
                return None, api_error(f'{key} cannot be empty.', status=400, code=f'missing_{key}')
            vals[key] = payload[key]
    if 'description' in payload:
        vals['description'] = payload['description'] or False
    if 'capacity' in payload:
        capacity, error = parse_int(payload['capacity'] or 0, 'capacity')
        if error:
            return None, error
        if capacity < 0:
            return None, api_error('capacity cannot be negative.', status=400, code='invalid_capacity')
        vals['capacity'] = capacity
    if 'class_teacher_id' in payload:
        teacher, error = resolve_record(env, 'op.faculty', payload['class_teacher_id'], 'class_teacher_id')
        if error:
            return None, error
        vals['class_teacher_id'] = teacher.id or False
    for key in ('start_date', 'end_date'):
        if payload.get(key):
            vals[key], error = parse_date(payload[key], key)
            if error:
                return None, error
    if 'active' in payload:
        vals['active'] = bool(payload['active'])
    if vals.get('code'):
        error = _check_code(env, 'op.batch', vals['code'], batch)
        if error:
            return None, error
    return vals, None


class BxiApiSupportAdminClassesController(http.Controller):

    def _get(self, model, record_id, label):
        record = request.env[model].sudo().with_context(active_test=False).browse(record_id)
        if not record.exists():
            return None, api_error(f'{label} not found.', status=404, code='not_found')
        return record, None

    def _class_detail(self, course):
        """The class with every section (archived ones flagged), each
        section's classroom and subject teachers from its timetable, and
        the class's subjects with their mapped teachers."""
        env = request.env
        sections = env['op.batch'].sudo().with_context(active_test=False).search(
            [('course_id', '=', course.id)], order='active desc, name')
        by_batch = _strength(env, 'batch_id', sections.ids)
        data = _class_dict(course, sections.filtered('active'), _strength(env, 'course_id', course.ids), by_batch)
        mappings = env['bxi.subject.mapping'].sudo().search([('class_id', '=', course.id)])
        data['subjects'] = [{
            'id': subject.id,
            'name': subject.name,
            'code': subject.code,
            'teachers': [ref(t) for t in mappings.filtered(lambda m: m.subject_id == subject).teacher_id],
        } for subject in course.subject_ids.sorted('name')]
        lines = env['bxi.timetable.line'].sudo().search([('timetable_id.batch_id', 'in', sections.ids)])
        classrooms = env['op.classroom'].sudo().search([('batch_id', 'in', sections.ids)])
        data['sections'] = []
        for batch in sections:
            pairs = []
            section_lines = lines.filtered(lambda line: line.timetable_id.batch_id == batch)
            for line in section_lines.sorted(lambda line: line.subject_id.name or ''):
                pair = {'subject': ref(line.subject_id), 'teacher': ref(line.teacher_id)}
                if pair not in pairs:
                    pairs.append(pair)
            data['sections'].append(dict(
                _section_dict(batch, by_batch),
                classroom=ref(classrooms.filtered(lambda r: r.batch_id == batch)[:1]),
                subject_teachers=pairs,
            ))
        return data

    @http.route('/api/v1/admin/classes', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_classes(self, q=None, department_id=None, program_id=None, academic_year_id=None, active='1',
                     expand=None, sort=None, **kwargs):
        """Classes with section/strength/capacity figures. The summary
        covers every class matching the filters, not just this page.
        ?academic_year_id= keeps classes with a section in that year;
        ?expand=sections nests each class's sections."""
        env = request.env
        if not _allowed(env.user, VIEW_GROUPS):
            return _forbidden()
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        order, error = parse_sort(sort, SORTS, 'name asc')
        if error:
            return error
        Batch = env['op.batch'].sudo().with_context(active_test=False)
        domain = _active_domain(active)
        if q:
            domain &= Domain('name', 'ilike', q) | Domain('code', 'ilike', q)
        for param, value in (('department_id', department_id), ('program_id', program_id)):
            if value:
                value, error = parse_int(value, param)
                if error:
                    return error
                domain &= Domain(param, '=', value)
        section_domain = Domain.TRUE if active in ('0', 'all') else Domain('active', '=', True)
        if academic_year_id:
            year, error = resolve_record(env, 'op.academic.year', academic_year_id, 'academic_year_id')
            if error:
                return error
            section_domain &= _year_domain(year)
            domain &= Domain('id', 'in', Batch.search(section_domain).course_id.ids)
        classes = env['op.course'].sudo().with_context(active_test=False).search(
            domain, order='%s %s, id' % (SORTS[order[0]], order[1]))
        sections = Batch.search(section_domain & Domain('course_id', 'in', classes.ids), order='name')
        by_course = _strength(env, 'course_id', classes.ids)
        by_batch = _strength(env, 'batch_id', sections.ids)
        expand = expand == 'sections'
        return api_response({
            'items': [_class_dict(c, sections.filtered(lambda b: b.course_id == c), by_course, by_batch, expand)
                      for c in classes[offset:offset + limit]],
            'summary': {
                'classes': len(classes),
                'sections': len(sections),
                'students': sum(by_course.values()),
                'capacity': sum(sections.mapped('capacity')),
                'sections_without_class_teacher': len(sections.filtered(lambda b: not b.class_teacher_id)),
            },
        }, meta={'total': len(classes), 'limit': limit, 'offset': offset})

    @http.route('/api/v1/admin/classes/<int:course_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_class(self, course_id, **kwargs):
        if not _allowed(request.env.user, VIEW_GROUPS):
            return _forbidden()
        course, error = self._get('op.course', course_id, 'Class')
        if error:
            return error
        return api_response(self._class_detail(course))

    @http.route('/api/v1/admin/sections/<int:batch_id>/students', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def section_students(self, batch_id, **kwargs):
        """The section's current students by roll number, with their
        parents' contact details."""
        env = request.env
        if not _allowed(env.user, VIEW_GROUPS):
            return _forbidden()
        batch, error = self._get('op.batch', batch_id, 'Section')
        if error:
            return error
        enrollments = env['op.student.course'].sudo().search(
            [('batch_id', '=', batch.id), ('state', '=', 'running')], order='roll_number, id')
        parents = env['op.parent'].sudo().search([('student_ids', 'in', enrollments.student_id.ids)])
        return api_response({
            'section': _section_dict(batch, {batch.id: len(enrollments)}),
            'students': [{
                'id': line.student_id.id,
                'name': line.student_id.name,
                'gr_no': line.student_id.gr_no or None,
                'roll_number': line.roll_number or None,
                'gender': line.student_id.gender,
                'email': line.student_id.email or None,
                'phone': line.student_id.phone or None,
                'parents': [{
                    'id': parent.id,
                    'name': parent.name.name,
                    'relationship': parent.relationship_id.name or None,
                    'mobile': parent.mobile or None,
                    'email': parent.email or None,
                } for parent in parents.filtered(lambda p: line.student_id in p.student_ids)],
            } for line in enrollments],
        })

    # -- add / edit ---------------------------------------------------------------

    @http.route('/api/v1/admin/classes', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_class(self, **kwargs):
        """{"name", "code", "department_id"?, "program_id"?, "parent_id"?,
        "evaluation_type"?, "subject_ids"?, "sections"?: [{"name", "code"?,
        "capacity"?, "class_teacher_id"?, "start_date"?, "end_date"?,
        "description"?}]} - the class and its sections are saved together
        or not at all."""
        env = request.env
        if not _allowed(env.user, EDIT_GROUPS):
            return _forbidden()
        payload = request.get_json_data() or {}
        for required in ('name', 'code'):
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        vals, error = _class_vals(env, payload)
        if error:
            return error
        sections = payload.get('sections') or []
        if not isinstance(sections, list):
            return api_error('sections must be a list.', status=400, code='invalid_sections')
        section_vals = []
        for entry in sections:
            if not isinstance(entry, dict) or not entry.get('name'):
                return api_error('Each section needs a name.', status=400, code='missing_name')
            entry_vals, error = _section_vals(env, entry)
            if error:
                return error
            section_vals.append(entry_vals)

        def create():
            course = env['op.course'].sudo().create(vals)
            env['op.batch'].sudo().create([dict(v, course_id=course.id) for v in section_vals])
            return course
        course, error = atomic(create)
        if error:
            return error
        return api_response(self._class_detail(course), status=201)

    @http.route('/api/v1/admin/classes/<int:course_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_class(self, course_id, **kwargs):
        """Any create field except sections, plus "active": false to
        archive the class."""
        env = request.env
        if not _allowed(env.user, EDIT_GROUPS):
            return _forbidden()
        course, error = self._get('op.course', course_id, 'Class')
        if error:
            return error
        vals, error = _class_vals(env, request.get_json_data() or {}, course)
        if error:
            return error
        _, error = atomic(lambda: course.write(vals))
        if error:
            return error
        return api_response(self._class_detail(course))

    @http.route('/api/v1/admin/sections', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_section(self, **kwargs):
        """{"class_id", "name", "code"?, "capacity"?, "class_teacher_id"?,
        "start_date"?, "end_date"?, "description"?}"""
        env = request.env
        if not _allowed(env.user, EDIT_GROUPS):
            return _forbidden()
        payload = request.get_json_data() or {}
        if not payload.get('class_id'):
            return api_error('class_id is required.', status=400, code='missing_class_id')
        if not payload.get('name'):
            return api_error('name is required.', status=400, code='missing_name')
        course, error = resolve_record(env, 'op.course', payload['class_id'], 'class_id')
        if error:
            return error
        vals, error = _section_vals(env, payload)
        if error:
            return error
        batch, error = atomic(lambda: env['op.batch'].sudo().create(dict(vals, course_id=course.id)))
        if error:
            return error
        return api_response(_section_dict(batch, {}), status=201)

    @http.route('/api/v1/admin/sections/<int:batch_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_section(self, batch_id, **kwargs):
        """Any create field except class_id (students are enrolled in the
        class and section together), plus "active": false to archive."""
        env = request.env
        if not _allowed(env.user, EDIT_GROUPS):
            return _forbidden()
        batch, error = self._get('op.batch', batch_id, 'Section')
        if error:
            return error
        payload = request.get_json_data() or {}
        if 'class_id' in payload and str(payload['class_id']) != str(batch.course_id.id):
            return api_error('A section cannot be moved to another class.', status=400, code='invalid_class_id')
        vals, error = _section_vals(env, payload, batch)
        if error:
            return error
        _, error = atomic(lambda: batch.write(vals))
        if error:
            return error
        return api_response(_section_dict(batch, _strength(env, 'batch_id', batch.ids)))
