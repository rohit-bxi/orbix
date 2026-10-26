# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""School directory for the office: students, teachers and parents - list,
create and update. Reads of a single student's full profile stay on
/students/<id>/profile (profile.py)."""
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, parse_int, require_auth

from .common import STUDENT_STAFF_GROUPS, date_str, parse_ids, parse_pagination, ref, safe_create, school_context
from .profile import student_summary

# Who may add and edit people records.
MANAGER_GROUPS = (
    'openeducat_core.group_op_back_office_admin',
    'bxi_academic_management.group_academic_manager',
    'base.group_system',
)
STUDENT_FIELDS = (
    'first_name', 'middle_name', 'last_name', 'gender', 'birth_date', 'email', 'phone', 'gr_no',
    'blood_group', 'admission_date', 'street', 'street2', 'city', 'zip', 'is_allergy', 'allergy',
    'id_number',
)
TEACHER_FIELDS = (
    'first_name', 'middle_name', 'last_name', 'gender', 'birth_date', 'email', 'phone', 'blood_group',
    'joining_date', 'highest_qualification', 'years_of_experience', 'id_number',
)
PARENT_FIELDS = ('mobile', 'email', 'gender', 'birth_date')
ID_FIELDS = ('nationality', 'state_id', 'country_id', 'main_department_id', 'relationship_id')


def _is_manager(user):
    return any(user.has_group(group) for group in MANAGER_GROUPS)


def _can_list_students(user):
    return any(user.has_group(group) for group in STUDENT_STAFF_GROUPS)


def _vals(payload, allowed):
    """(vals, error) from the allowed plain fields plus any *_id fields."""
    vals = {k: payload[k] for k in allowed if k in payload}
    for key in ID_FIELDS:
        if payload.get(key):
            vals[key], error = parse_int(payload[key], key)
            if error:
                return None, error
    return vals, None


def _teacher_dict(faculty):
    return {
        'id': faculty.id,
        'name': faculty.name,
        'email': faculty.email or None,
        'phone': faculty.phone or None,
        'gender': faculty.gender,
        'department': ref(faculty.main_department_id),
        'subjects': [ref(s) for s in faculty.faculty_subject_ids],
        'joining_date': date_str(faculty.joining_date),
        'has_login': bool(faculty.user_id),
    }


def _parent_dict(parent):
    return {
        'id': parent.id,
        'name': parent.name.name,
        'email': parent.email or parent.name.email or None,
        'mobile': parent.mobile or None,
        'relationship': ref(parent.relationship_id),
        'students': [ref(s) for s in parent.student_ids],
        'has_login': bool(parent.user_id),
    }


class BxiApiSupportPeopleController(http.Controller):

    # -- students ---------------------------------------------------------------

    @http.route('/api/v1/students', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_students(self, q=None, course_id=None, batch_id=None, **kwargs):
        """Office staff: every student. Teachers: the sections they teach."""
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = []
        if not _can_list_students(request.env.user):
            context = school_context(request.env)
            if not context['faculty']:
                return api_error('Not authorized to list students.', status=403, code='forbidden')
            domain += [('course_detail_ids.batch_id', 'in', context['teaching_batches'].ids),
                       ('course_detail_ids.state', '=', 'running')]
        for param, raw, field in (('course_id', course_id, 'course_detail_ids.course_id'),
                                  ('batch_id', batch_id, 'course_detail_ids.batch_id')):
            if raw:
                value, error = parse_int(raw, param)
                if error:
                    return error
                domain.append((field, '=', value))
        if q:
            domain += ['|', '|', ('name', 'ilike', q), ('gr_no', 'ilike', q), ('email', 'ilike', q)]
        Student = request.env['op.student'].sudo()
        total = Student.search_count(domain)
        students = Student.search(domain, limit=limit, offset=offset, order='name')
        return api_response({'students': [student_summary(s) for s in students]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/students', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_student(self, **kwargs):
        """Office creates a student, optionally enrolled straight away:
        {"first_name", "last_name", "gender", ..., "enrollment": {"course_id",
        "batch_id", "roll_number"?, "academic_year_id"?}}."""
        if not _is_manager(request.env.user):
            return api_error('Not authorized to add students.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        for required in ('first_name', 'last_name', 'gender'):
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        vals, error = _vals(payload, STUDENT_FIELDS)
        if error:
            return error
        enrollment = payload.get('enrollment') or {}
        if enrollment:
            line = {}
            for key in ('course_id', 'batch_id', 'academic_year_id'):
                if enrollment.get(key):
                    line[key if key != 'academic_year_id' else 'academic_years_id'], error = parse_int(enrollment[key], key)
                    if error:
                        return error
            if not line.get('course_id'):
                return api_error('enrollment.course_id is required.', status=400, code='missing_course_id')
            line['roll_number'] = enrollment.get('roll_number') or False
            vals['course_detail_ids'] = [(0, 0, line)]
        student, error = safe_create(request.env['op.student'].sudo(), vals)
        if error:
            return error
        return api_response(student_summary(student), status=201)

    @http.route('/api/v1/students/<int:student_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_student(self, student_id, **kwargs):
        if not _is_manager(request.env.user):
            return api_error('Not authorized to edit students.', status=403, code='forbidden')
        student = request.env['op.student'].sudo().browse(student_id)
        if not student.exists():
            return api_error('Student not found.', status=404, code='not_found')
        vals, error = _vals(request.get_json_data() or {}, STUDENT_FIELDS)
        if error:
            return error
        _, error = call_action(student, 'write', vals=vals)
        if error:
            return error
        return api_response(student_summary(student))

    # -- teachers -----------------------------------------------------------------

    @http.route('/api/v1/teachers', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_teachers(self, q=None, **kwargs):
        """Any staff login - e.g. to pick a colleague - but not families."""
        if not request.env.user._bxi_is_staff():
            return api_error('Not authorized to list teachers.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [('name', 'ilike', q)] if q else []
        Faculty = request.env['op.faculty'].sudo()
        total = Faculty.search_count(domain)
        teachers = Faculty.search(domain, limit=limit, offset=offset, order='name')
        return api_response({'teachers': [_teacher_dict(t) for t in teachers]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/teachers/<int:faculty_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_teacher(self, faculty_id, **kwargs):
        if not request.env.user._bxi_is_staff():
            return api_error('Not authorized for this teacher.', status=403, code='forbidden')
        faculty = request.env['op.faculty'].sudo().browse(faculty_id)
        if not faculty.exists():
            return api_error('Teacher not found.', status=404, code='not_found')
        return api_response(_teacher_dict(faculty))

    @http.route('/api/v1/teachers', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_teacher(self, **kwargs):
        if not _is_manager(request.env.user):
            return api_error('Not authorized to add teachers.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        for required in ('first_name', 'last_name', 'gender', 'birth_date'):
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        vals, error = _vals(payload, TEACHER_FIELDS)
        if error:
            return error
        if payload.get('subject_ids'):
            subject_ids, error = parse_ids(payload['subject_ids'], 'subject_ids')
            if error:
                return error
            vals['faculty_subject_ids'] = [(6, 0, subject_ids)]
        faculty, error = safe_create(request.env['op.faculty'].sudo(), vals)
        if error:
            return error
        return api_response(_teacher_dict(faculty), status=201)

    @http.route('/api/v1/teachers/<int:faculty_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_teacher(self, faculty_id, **kwargs):
        if not _is_manager(request.env.user):
            return api_error('Not authorized to edit teachers.', status=403, code='forbidden')
        faculty = request.env['op.faculty'].sudo().browse(faculty_id)
        if not faculty.exists():
            return api_error('Teacher not found.', status=404, code='not_found')
        payload = request.get_json_data() or {}
        vals, error = _vals(payload, TEACHER_FIELDS)
        if error:
            return error
        if 'subject_ids' in payload:
            subject_ids, error = parse_ids(payload['subject_ids'] or [], 'subject_ids')
            if error:
                return error
            vals['faculty_subject_ids'] = [(6, 0, subject_ids)]
        _, error = call_action(faculty, 'write', vals=vals)
        if error:
            return error
        return api_response(_teacher_dict(faculty))

    # -- parents ------------------------------------------------------------------

    @http.route('/api/v1/parents', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_parents(self, q=None, student_id=None, **kwargs):
        if not _can_list_students(request.env.user):
            return api_error('Not authorized to list parents.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = []
        if q:
            domain += ['|', '|', ('name.name', 'ilike', q), ('mobile', 'ilike', q), ('email', 'ilike', q)]
        if student_id:
            student_id, error = parse_int(student_id, 'student_id')
            if error:
                return error
            domain.append(('student_ids', 'in', student_id))
        Parent = request.env['op.parent'].sudo()
        total = Parent.search_count(domain)
        parents = Parent.search(domain, limit=limit, offset=offset)
        return api_response({'parents': [_parent_dict(p) for p in parents]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/parents', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_parent(self, **kwargs):
        """{"name", "mobile", "email"?, "relationship_id", "student_ids",
        "create_login"?}: a parent record linked to their children; with
        create_login, also the portal login they use for the app."""
        if not _is_manager(request.env.user):
            return api_error('Not authorized to add parents.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        for required in ('name', 'mobile', 'relationship_id', 'student_ids'):
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        vals, error = _vals(payload, PARENT_FIELDS)
        if error:
            return error
        student_ids, error = parse_ids(payload['student_ids'], 'student_ids')
        if error:
            return error
        partner = request.env['res.partner'].sudo().create({
            'name': payload['name'], 'email': payload.get('email') or False, 'phone': payload['mobile'],
            'is_parent': True,
        })
        vals.update({'name': partner.id, 'student_ids': [(6, 0, student_ids)]})
        parent, error = safe_create(request.env['op.parent'].sudo(), vals)
        if error:
            return error
        if payload.get('create_login'):
            _, error = call_action(parent, 'create_parent_user')
            if error:
                return error
        return api_response(_parent_dict(parent), status=201)

    @http.route('/api/v1/parents/<int:parent_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_parent(self, parent_id, **kwargs):
        if not _is_manager(request.env.user):
            return api_error('Not authorized to edit parents.', status=403, code='forbidden')
        parent = request.env['op.parent'].sudo().browse(parent_id)
        if not parent.exists():
            return api_error('Parent not found.', status=404, code='not_found')
        payload = request.get_json_data() or {}
        vals, error = _vals(payload, PARENT_FIELDS)
        if error:
            return error
        if 'student_ids' in payload:
            student_ids, error = parse_ids(payload['student_ids'] or [], 'student_ids')
            if error:
                return error
            vals['student_ids'] = [(6, 0, student_ids)]
        _, error = call_action(parent, 'write', vals=vals)
        if error:
            return error
        if 'name' in payload and payload['name']:
            parent.name.name = payload['name']
        return api_response(_parent_dict(parent))
