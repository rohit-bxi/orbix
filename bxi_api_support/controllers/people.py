# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""School directory for the office: students, teachers and parents - list,
create, update and photos. Reads of a single student's full profile for
families and teachers stay on /students/<id>/profile (profile.py).

Create/update bodies are JSON. The plain profile keys each kind accepts,
and how they read back, are declared in people_fields.py. Common blocks:
  "image": "<base64>" (a data: URL prefix is accepted; null clears it)
  "address": {"street", "street2", "city", "zip", "state_id", "country_id"}
  "health", "emergency_contact", "documents" (students/parents): see
            people_fields.py
  "status": teacher employment status / student enrolment state /
            parent "active" | "inactive". Whether someone can sign in
            (Account Status) is a separate login setting.
  "account", "face", "id_verification", "aadhaar_number" (and
            "documents" for teachers): Account & Security - see
            people_account.py.
Everything a request asks for is saved together or not at all; login
credentials are sent only once it is saved.
"""
import base64
import binascii

from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth

from odoo.addons.bxi_api.controllers.auth import api_file_response

from ..models.people_service import PeopleError
from ..models.res_users import TEACHER_PERMISSION_FIELDS
from .common import (
    STUDENT_STAFF_GROUPS, check_selection, date_str, parse_ids, parse_pagination, ref, resolve_record,
    resolve_records, running_enrollment, school_context, json_body,
)
from .people_account import (
    apply_aadhaar, apply_account, apply_documents, apply_face, apply_id_verification, deliver,
    document_dict, is_manager, parse_aadhaar, parse_account, parse_documents, parse_face, parse_id_verification,
    security_dict, transaction,
)
from .people_fields import (
    DOCUMENT_SETS, PARENT_SPEC, REQUIRED, STUDENT_SPEC, TEACHER_ADDRESSES, TEACHER_SPEC, WEEKDAYS, address_dict,
    apply_document_sets, documents_dict, emergency_contact_dict, fields_dict, health_dict, parse_address,
    parse_available_days, parse_document_sets, parse_fields, parse_health, parse_rte, parse_teacher_addresses,
    rte_dict,
)
from .profile import _image_response, _student_detail, student_summary


def _can_list_students(user):
    return any(user.has_group(group) for group in STUDENT_STAFF_GROUPS)


def _security_blocks(payload, teacher=False):
    """(blocks, error): the parsed Account & Security blocks of a body."""
    blocks = {}
    for key, parser in (('account', parse_account), ('face', parse_face),
                        ('id_verification', parse_id_verification), ('aadhaar', parse_aadhaar)):
        blocks[key], error = parser(payload)
        if error:
            return None, error
    blocks['documents'] = None
    if teacher:
        blocks['documents'], error = parse_documents(payload.get('documents'))
        if error:
            return None, error
    return blocks, None


def _require_login(blocks):
    """Students and parents are created together with their login: the
    requirement sheet marks Create Username and Create Password as
    mandatory. The password is still a one-time password."""
    account = blocks['account'] or {}
    for key in ('username', 'password'):
        if not account.get(key):
            return api_error(f'account.{key} is required.', status=400, code=f'missing_{key}')
    account['create_login'] = True
    return None


def _apply_security(record, blocks):
    """Apply parsed blocks inside the transaction; returns the credentials
    still to deliver."""
    apply_aadhaar(record, blocks['aadhaar'])
    delivery = apply_account(record, blocks['account'])
    apply_face(record, blocks['face'])
    apply_id_verification(record, blocks['id_verification'])
    if blocks['documents']:
        apply_documents(record, blocks['documents'])
    return delivery


def _with_credentials(data, record, delivery):
    credentials = deliver(record, delivery)
    if credentials is not None:
        data['credentials'] = credentials
    return data


def _image_value(payload):
    """(vals, error): {'image_1920': base64 or False} when the payload has
    an "image" key. Whether the bytes are really an image is checked by the
    field itself when written (a 400 through atomic())."""
    if 'image' not in payload:
        return {}, None
    value = payload['image']
    if not value:
        return {'image_1920': False}, None
    if not isinstance(value, str):
        return None, api_error('image must be a base64 string.', status=400, code='invalid_image')
    if value.startswith('data:') and ';base64,' in value:
        value = value.split(';base64,', 1)[1]
    value = ''.join(value.split())
    try:
        base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None, api_error('image must be a base64 string.', status=400, code='invalid_image')
    return {'image_1920': value}, None


def _profile_vals(Model, payload, spec, *builders):
    """(vals, error): the spec's plain fields, then each builder's
    (Model, payload) -> (vals, error)."""
    vals, error = parse_fields(Model, payload, spec, required=REQUIRED[Model._name])
    if error:
        return None, error
    for builder in builders:
        extra, error = builder(Model, payload)
        if error:
            return None, error
        vals.update(extra)
    return vals, None


def _image_builder(Model, payload):
    return _image_value(payload)


def _email_taken(email, partner=None):
    """An email already used by another contact (the core student/teacher
    records require it to be unique, and it becomes the login)."""
    if not email:
        return False
    domain = [('email', '=ilike', email.strip())]
    if partner:
        domain.append(('id', '!=', partner.id))
    return bool(request.env['res.partner'].sudo().with_context(active_test=False).search_count(domain, limit=1))


def _email_taken_error():
    return api_error('This email is already used by another person.', status=409, code='email_taken')


def _emergency_contact(payload, record=None):
    """(vals, contact, error) for an optional "emergency_contact": {"name",
    "phone", "relation" (teachers)}. null / {} removes it (vals); an object
    is applied once the record is written (contact)."""
    if 'emergency_contact' not in payload:
        return {}, None, None
    contact = payload['emergency_contact']
    if not contact:
        vals = {'emergency_contact': False}
        if record is not None and 'emergency_contact_relation' in record._fields:
            vals['emergency_contact_relation'] = False
        return vals, None, None
    if not isinstance(contact, dict):
        return None, None, api_error('emergency_contact must be an object.', status=400,
                                     code='invalid_emergency_contact')
    if not (record and record.emergency_contact) and not str(contact.get('name') or '').strip():
        return None, None, api_error('emergency_contact.name is required.', status=400,
                                     code='missing_emergency_contact_name')
    return {}, contact, None


def _apply_emergency_contact(record, contact):
    """Create or update the emergency-contact person of a teacher or
    student. A blank name on an existing contact leaves the name as it is."""
    if not contact:
        return
    partner_vals = {}
    name = str(contact.get('name') or '').strip()
    if name:
        partner_vals['name'] = name
    if 'phone' in contact:
        partner_vals['phone'] = contact['phone'] or False
    if record.emergency_contact:
        if partner_vals:
            record.emergency_contact.write(partner_vals)
    else:
        record.emergency_contact = request.env['res.partner'].sudo().create(partner_vals)
    if 'relation' in contact and 'emergency_contact_relation' in record._fields:
        record.emergency_contact_relation = contact['relation'] or False


# -- teachers -----------------------------------------------------------------------------


def _teacher_dict(faculty):
    return {
        'id': faculty.id,
        'name': faculty.name,
        'email': faculty.email or None,
        'phone': faculty.phone or None,
        'gender': faculty.gender,
        'department': ref(faculty.main_department_id),
        'designation': ref(faculty.designation_id),
        'subjects': [ref(s) for s in faculty.faculty_subject_ids],
        'joining_date': date_str(faculty.joining_date),
        'status': faculty.employment_status,
        'has_photo': bool(faculty.image_128),
        'has_login': bool(faculty.user_id),
        'login_active': bool(faculty.user_id.active),
    }


def _teacher_detail(faculty):
    data = _teacher_dict(faculty)
    class_teacher_of = request.env['op.batch'].sudo().search([('class_teacher_id', '=', faculty.id)])
    data.update({
        'age': faculty.age or None,
        'address': address_dict(faculty),
        'emergency_contact': emergency_contact_dict(faculty),
        'specialization': ref(faculty.faculty_subject_id),
        'assignments': {
            'classes': [ref(c) for c in faculty.assigned_course_ids],
            'sections': [ref(b) for b in faculty.assigned_batch_ids],
            'class_teacher_of': [ref(b) for b in class_teacher_of],
        },
        'workload': {
            'max_weekly_periods': faculty.max_weekly_periods,
            'assigned_periods': faculty.weekly_period_count,
            'remaining_periods': faculty.remaining_weekly_periods,
            'workload_status': faculty.workload_status,
            'timetable_auto_assign': faculty.timetable_auto_assign,
            'available_days': [day for day in WEEKDAYS if faculty['available_%s' % day]],
        },
        'responsibilities': [ref(r) for r in faculty.responsibility_ids],
        'notes': faculty.staff_notes or None,
        'permissions': {key: faculty[field] for key, field in TEACHER_PERMISSION_FIELDS.items()},
        'health': health_dict(faculty),
        'documents': [document_dict(d) for d in faculty.document_ids],
    })
    for name in TEACHER_ADDRESSES:
        data['%s_address' % name] = address_dict(faculty, prefix='%s_' % name)
    for key, value in fields_dict(faculty, TEACHER_SPEC).items():
        data.setdefault(key, value)
    data.update(security_dict(faculty))
    return data


def _teacher_extra_vals(Model, payload, faculty=None):
    """(vals, error) for the teacher's relations and nested objects."""
    vals = {}
    if 'notes' in payload:
        vals['staff_notes'] = payload['notes'] or False
    if 'subject_ids' in payload:
        subjects, error = resolve_records(request.env, 'op.subject', payload['subject_ids'], 'subject_ids')
        if error:
            return None, error
        vals['faculty_subject_ids'] = [(6, 0, subjects.ids)]
    for key, field, model in (('specialization_subject_id', 'faculty_subject_id', 'op.subject'),
                              ('designation_id', 'designation_id', 'hr.job')):
        if key in payload:
            record, error = resolve_record(request.env, model, payload[key], key)
            if error:
                return None, error
            vals[field] = record.id or False
    if 'responsibility_ids' in payload:
        records, error = resolve_records(
            request.env, 'bxi.staff.responsibility', payload['responsibility_ids'], 'responsibility_ids')
        if error:
            return None, error
        vals['responsibility_ids'] = [(6, 0, records.ids)]
    if 'status' in payload:
        error = check_selection(Model, 'employment_status', payload['status'], key='status')
        if error:
            return None, error
        vals['employment_status'] = payload['status']

    assignments = payload.get('assignments')
    if assignments is not None:
        if not isinstance(assignments, dict):
            return None, api_error('assignments must be an object.', status=400, code='invalid_assignments')
        courses = faculty.assigned_course_ids if faculty else request.env['op.course']
        batches = faculty.assigned_batch_ids if faculty else request.env['op.batch']
        if 'course_ids' in assignments:
            courses, error = resolve_records(request.env, 'op.course', assignments['course_ids'], 'course_ids')
            if error:
                return None, error
        if 'batch_ids' in assignments:
            batches, error = resolve_records(request.env, 'op.batch', assignments['batch_ids'], 'batch_ids')
            if error:
                return None, error
        # A section implies its class, so the app can send sections alone.
        vals['assigned_course_ids'] = [(6, 0, (courses | batches.course_id).ids)]
        vals['assigned_batch_ids'] = [(6, 0, batches.ids)]

    permissions = payload.get('permissions')
    if permissions is not None:
        if not isinstance(permissions, dict) or set(permissions) - set(TEACHER_PERMISSION_FIELDS):
            return None, api_error(
                'permissions must be an object with keys %s.' % ', '.join(TEACHER_PERMISSION_FIELDS),
                status=400, code='invalid_permissions')
        for key, value in permissions.items():
            vals[TEACHER_PERMISSION_FIELDS[key]] = bool(value)

    workload = payload.get('workload')
    if workload is not None:
        if not isinstance(workload, dict):
            return None, api_error('workload must be an object.', status=400, code='invalid_workload')
        if 'max_weekly_periods' in workload:
            limit, error = parse_int(workload['max_weekly_periods'], 'max_weekly_periods')
            if error:
                return None, error
            if limit < 0:
                return None, api_error('max_weekly_periods cannot be negative.', status=400,
                                       code='invalid_max_weekly_periods')
            vals['max_weekly_periods'] = limit
        if 'timetable_auto_assign' in workload:
            vals['timetable_auto_assign'] = bool(workload['timetable_auto_assign'])
        if 'available_days' in workload:
            days, error = parse_available_days(workload['available_days'])
            if error:
                return None, error
            vals.update(days)
    return vals, None


def _teacher_vals(payload, faculty=None):
    """(vals, emergency_contact, error) for a teacher create (faculty=None)
    or update. emergency_contact is the payload's object, applied after the
    record is written; None when absent."""
    vals, error = _profile_vals(
        request.env['op.faculty'], payload, TEACHER_SPEC, _image_builder, parse_address,
        parse_teacher_addresses, parse_health, lambda Model, body: _teacher_extra_vals(Model, body, faculty))
    if error:
        return None, None, error
    extra, contact, error = _emergency_contact(payload, faculty)
    if error:
        return None, None, error
    vals.update(extra)
    return vals, contact, None


# -- students -----------------------------------------------------------------------------


def _current_enrollment(student):
    """The running enrolment, else the one finished last (see
    op.student._bxi_current_enrolment in bxi_people_management)."""
    return student._bxi_current_enrolment()


def _student_admin_dict(student):
    data = _student_detail(student)
    current = _current_enrollment(student)
    data.update({
        'status': current.state or None,
        'department': ref(current.course_id.department_id),
        'certificate_number': student.certificate_number or None,
        'emergency_contact': emergency_contact_dict(student),
        'health': health_dict(student),
        'documents': documents_dict(student),
    })
    for key, value in fields_dict(student, STUDENT_SPEC).items():
        data.setdefault(key, value)
    data.update(security_dict(student))
    return data


def _student_vals(payload, student=None):
    """(vals, emergency_contact, document_sets, error) for a student create
    (student=None) or update."""
    Student = request.env['op.student']
    vals, error = _profile_vals(Student, payload, STUDENT_SPEC, _image_builder, parse_address, parse_health)
    if error:
        return None, None, None, error
    extra, contact, error = _emergency_contact(payload, student)
    if error:
        return None, None, None, error
    vals.update(extra)
    documents, error = parse_document_sets('op.student', payload)
    if error:
        return None, None, None, error
    return vals, contact, documents, None


def _enrollment_line(enrollment):
    """(op.student.course vals, error) for a new student's enrolment: class,
    section and roll number are all required, and the section must belong
    to the class."""
    if not isinstance(enrollment, dict):
        return None, api_error('enrollment is required.', status=400, code='missing_enrollment')
    for key in ('course_id', 'batch_id', 'roll_number'):
        if not enrollment.get(key):
            return None, api_error(f'enrollment.{key} is required.', status=400, code=f'missing_{key}')
    course, error = resolve_record(request.env, 'op.course', enrollment['course_id'], 'course_id')
    if error:
        return None, error
    batch, error = resolve_record(request.env, 'op.batch', enrollment['batch_id'], 'batch_id')
    if error:
        return None, error
    if batch.course_id != course:
        return None, api_error('This section does not belong to that class.', status=400,
                               code='batch_course_mismatch')
    line = {'course_id': course.id, 'batch_id': batch.id, 'roll_number': str(enrollment['roll_number']).strip()}
    if enrollment.get('academic_year_id'):
        year, error = resolve_record(request.env, 'op.academic.year', enrollment['academic_year_id'],
                                     'academic_year_id')
        if error:
            return None, error
        line['academic_years_id'] = year.id
    return line, None


def _transfer(student, transfer):
    """Move a student to another section (optionally another class): the
    current enrolment is finished and a running one opened for the new
    section, so attendance and results keep their history. Re-entering a
    section the student was in before reopens that enrolment. Raises
    UserError-family exceptions; returns an api_error for bad input."""
    if not isinstance(transfer, dict) or not transfer.get('batch_id'):
        return api_error('transfer.batch_id is required.', status=400, code='missing_batch_id')
    batch, error = resolve_record(request.env, 'op.batch', transfer['batch_id'], 'batch_id')
    if error:
        return error
    course = batch.course_id
    if transfer.get('course_id'):
        course, error = resolve_record(request.env, 'op.course', transfer['course_id'], 'course_id')
        if error:
            return error
        if batch.course_id != course:
            return api_error('This section does not belong to that class.', status=400,
                             code='batch_course_mismatch')
    roll_number = str(transfer.get('roll_number') or '').strip() or False
    current = running_enrollment(student)
    if current and current.course_id == course and current.batch_id == batch:
        if roll_number:
            current.roll_number = roll_number
        return None
    previous = student.course_detail_ids.filtered(lambda l: l.course_id == course and l.batch_id == batch)[:1]
    if not previous and not roll_number:
        return api_error('transfer.roll_number is required.', status=400, code='missing_roll_number')
    if current:
        current.state = 'finished'
    if previous:
        previous.write({'state': 'running', 'roll_number': roll_number or previous.roll_number})
        return None
    line = {
        'student_id': student.id, 'course_id': course.id, 'batch_id': batch.id, 'roll_number': roll_number,
        'state': 'running', 'academic_years_id': current.academic_years_id.id,
        'academic_term_id': current.academic_term_id.id,
    }
    if current.course_id == course:
        line.update({'subject_ids': [(6, 0, current.subject_ids.ids)], 'fees_term_id': current.fees_term_id.id})
    request.env['op.student.course'].sudo().create(line)
    return None


def _student_record(student_id):
    student = request.env['op.student'].sudo().with_context(active_test=False).browse(student_id)
    return student if student.exists() else None


# -- parents ------------------------------------------------------------------------------


def _parent_dict(parent):
    enrollments = parent.student_ids.course_detail_ids.filtered(lambda line: line.state == 'running')
    return {
        'id': parent.id,
        'name': parent.name.name,
        'email': parent.email or parent.name.email or None,
        'mobile': parent.mobile or None,
        'relationship': ref(parent.relationship_id),
        'students': [ref(s) for s in parent.student_ids],
        # Read-only, from the children's running enrolments.
        'departments': [ref(d) for d in enrollments.course_id.department_id],
        'classes': [{'student': ref(line.student_id), 'class': ref(line.course_id), 'section': ref(line.batch_id)}
                    for line in enrollments],
        'status': 'active' if parent.active else 'inactive',
        'has_photo': bool(parent.name.image_128),
        'has_login': bool(parent.user_id),
        'login_active': bool(parent.user_id.active),
    }


def _parent_detail(parent):
    data = _parent_dict(parent)
    data.update({
        'address': address_dict(parent),
        'rte': rte_dict(parent),
        'documents': documents_dict(parent),
    })
    for key, value in fields_dict(parent, PARENT_SPEC).items():
        data.setdefault(key, value)
    data.update(security_dict(parent))
    return data


def _parent_status(Model, payload):
    """(vals, error) for an optional parent "status"."""
    if 'status' not in payload:
        return {}, None
    if payload['status'] not in ('active', 'inactive'):
        return None, api_error('status must be one of active, inactive.', status=400, code='invalid_status')
    return {'active': payload['status'] == 'active'}, None


def _parent_students(Model, payload):
    if 'student_ids' not in payload:
        return {}, None
    student_ids, error = parse_ids(payload['student_ids'] or [], 'student_ids')
    if error:
        return None, error
    if not student_ids:
        return None, api_error('student_ids is required.', status=400, code='missing_student_ids')
    students, error = resolve_records(request.env, 'op.student', student_ids, 'student_ids')
    if error:
        return None, error
    return {'student_ids': [(6, 0, students.ids)]}, None


def _parent_vals(payload):
    """(vals, partner_vals, document_sets, error) for a parent create or
    update. partner_vals go to the parent's contact: name, photo, and the
    email/mobile login credentials are sent to."""
    vals, error = _profile_vals(request.env['op.parent'], payload, PARENT_SPEC, parse_address, parse_rte,
                                _parent_status, _parent_students)
    if error:
        return None, None, None, error
    partner_vals, error = _image_value(payload)
    if error:
        return None, None, None, error
    if 'name' in payload:
        name = str(payload['name'] or '').strip()
        if not name:
            return None, None, None, api_error('name is required.', status=400, code='missing_name')
        partner_vals['name'] = name
    if 'email' in vals:
        partner_vals['email'] = vals['email']
    if 'mobile' in vals:
        partner_vals['phone'] = vals['mobile']
    documents, error = parse_document_sets('op.parent', payload)
    if error:
        return None, None, None, error
    return vals, partner_vals, documents, None


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
        """Office creates and enrols a student: {"first_name", "last_name",
        "gender", "email", ..., "image"?, "address"?, "enrollment":
        {"course_id", "batch_id", "roll_number", "academic_year_id"?},
        "account": {"username", "password", "active"?, "send_credentials"?,
        "channel"?}} - email, class, section, roll number, username and
        password are required. Every update field is accepted too."""
        if not is_manager(request.env.user):
            return api_error('Not authorized to add students.', status=403, code='forbidden')
        payload = json_body() or {}
        for required in REQUIRED['op.student']:
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        vals, contact, documents, error = _student_vals(payload)
        if error:
            return error
        line, error = _enrollment_line(payload.get('enrollment'))
        if error:
            return error
        blocks, error = _security_blocks(payload)
        if error:
            return error
        error = _require_login(blocks)
        if error:
            return error
        if _email_taken(payload['email']):
            return _email_taken_error()
        vals['course_detail_ids'] = [(0, 0, line)]

        def create():
            student = request.env['op.student'].sudo().create(vals)
            _apply_emergency_contact(student, contact)
            apply_document_sets(student, documents)
            return student, _apply_security(student, blocks)

        result, error = transaction(create)
        if error:
            return error
        student, delivery = result
        return api_response(_with_credentials(_student_admin_dict(student), student, delivery), status=201)

    @http.route('/api/v1/students/<int:student_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_student(self, student_id, **kwargs):
        """Office staff: the full student record, as create/update return it
        (families and teachers use /students/<id>/profile)."""
        if not _can_list_students(request.env.user):
            return api_error('Not authorized for this student.', status=403, code='forbidden')
        student = _student_record(student_id)
        if not student:
            return api_error('Student not found.', status=404, code='not_found')
        return api_response(_student_admin_dict(student))

    @http.route('/api/v1/students/<int:student_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_student(self, student_id, **kwargs):
        """Any of the create fields (people_fields.STUDENT_SPEC, plus "image",
        "address", "health", "emergency_contact": {"name", "phone"},
        "documents": {"birth_certificate", "transfer_certificate",
        "previous_school_certificate", "medical_records"} and the Account &
        Security blocks), plus "transfer": {"batch_id", "course_id"?,
        "roll_number"} to move the student to another section, and
        "status": "running" | "finished" for the current enrolment. Only the
        keys sent are changed."""
        if not is_manager(request.env.user):
            return api_error('Not authorized to edit students.', status=403, code='forbidden')
        student = _student_record(student_id)
        if not student:
            return api_error('Student not found.', status=404, code='not_found')
        payload = json_body() or {}
        vals, contact, documents, error = _student_vals(payload, student)
        if error:
            return error
        if vals.get('email') and _email_taken(vals['email'], student.partner_id):
            return _email_taken_error()
        status = payload.get('status')
        if 'status' in payload:
            error = check_selection(request.env['op.student.course'], 'state', status, key='status')
            if error:
                return error
        blocks, error = _security_blocks(payload)
        if error:
            return error

        def apply():
            if vals:
                student.write(vals)
            _apply_emergency_contact(student, contact)
            apply_document_sets(student, documents)
            if 'transfer' in payload:
                error = _transfer(student, payload['transfer'])
                if error:
                    # Roll back what was already written.
                    raise PeopleError(None, None, response=error)
            if status:
                current = _current_enrollment(student)
                if not current:
                    raise PeopleError('This student has no enrolment.', 'no_enrollment')
                current.state = status
            return _apply_security(student, blocks)

        delivery, error = transaction(apply)
        if error:
            return error
        return api_response(_with_credentials(_student_admin_dict(student), student, delivery))

    @http.route('/api/v1/<any("students", "parents"):kind>/<int:record_id>/documents/<int:attachment_id>',
                type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def person_document(self, kind, record_id, attachment_id, **kwargs):
        """Download one file of a student's or parent's "documents" sets."""
        if not _can_list_students(request.env.user):
            return api_error('Not authorized for these documents.', status=403, code='forbidden')
        model = 'op.student' if kind == 'students' else 'op.parent'
        record = request.env[model].sudo().with_context(active_test=False).browse(record_id).exists()
        if not record:
            return api_error('Not found.', status=404, code='not_found')
        attachments = request.env['ir.attachment'].sudo()
        for field in DOCUMENT_SETS[model].values():
            attachments |= record[field]
        attachment = attachments.filtered(lambda a: a.id == attachment_id)
        if not attachment:
            return api_error('Document not found.', status=404, code='not_found')
        return api_file_response(attachment.raw, attachment.name, attachment.mimetype or 'application/octet-stream')

    # -- teachers -----------------------------------------------------------------

    @http.route('/api/v1/teachers', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_teachers(self, q=None, status=None, **kwargs):
        """Any staff login - e.g. to pick a colleague - but not families."""
        if not request.env.user._bxi_is_staff():
            return api_error('Not authorized to list teachers.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [('name', 'ilike', q)] if q else []
        if status:
            error = check_selection(request.env['op.faculty'], 'employment_status', status, key='status')
            if error:
                return error
            domain.append(('employment_status', '=', status))
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
        return api_response(_teacher_detail(faculty))

    @http.route('/api/v1/teachers/<int:faculty_id>/photo', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def teacher_photo(self, faculty_id, **kwargs):
        if not request.env.user._bxi_is_staff():
            return api_error('Not authorized for this teacher.', status=403, code='forbidden')
        faculty = request.env['op.faculty'].sudo().browse(faculty_id)
        if not faculty.exists():
            return api_error('Teacher not found.', status=404, code='not_found')
        return _image_response(faculty.image_512, f'teacher-{faculty.id}.png')

    @http.route('/api/v1/teachers', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_teacher(self, **kwargs):
        """{"first_name", "last_name", "gender", "birth_date", "email"?,
        "image"?, "address"?, "emergency_contact"?: {"name", "phone",
        "relation"}, "highest_qualification"?, "specialization_subject_id"?,
        "subject_ids"?, "years_of_experience"?, "previous_school"?,
        "certifications"?, "assignments"?: {"course_ids", "batch_ids"},
        "workload"?: {"max_weekly_periods", "timetable_auto_assign"},
        "designation_id"?, "responsibility_ids"?, "status"?, "notes"?} - and
        every update field."""
        if not is_manager(request.env.user):
            return api_error('Not authorized to add teachers.', status=403, code='forbidden')
        payload = json_body() or {}
        for required in REQUIRED['op.faculty']:
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        vals, contact, error = _teacher_vals(payload)
        if error:
            return error
        blocks, error = _security_blocks(payload, teacher=True)
        if error:
            return error
        if _email_taken(vals.get('email')):
            return _email_taken_error()

        def create():
            faculty = request.env['op.faculty'].sudo().create(vals)
            _apply_emergency_contact(faculty, contact)
            return faculty, _apply_security(faculty, blocks)

        result, error = transaction(create)
        if error:
            return error
        faculty, delivery = result
        return api_response(_with_credentials(_teacher_detail(faculty), faculty, delivery), status=201)

    @http.route('/api/v1/teachers/<int:faculty_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_teacher(self, faculty_id, **kwargs):
        """Any of the create fields (people_fields.TEACHER_SPEC, plus "image",
        "address", "official_address", "postal_address", "regional_address",
        "health", "emergency_contact", "subject_ids",
        "specialization_subject_id", "designation_id", "responsibility_ids",
        "status", "notes", "assignments", "permissions", "workload":
        {"max_weekly_periods", "timetable_auto_assign", "available_days"},
        "documents" and the Account & Security blocks); only the keys sent
        are changed."""
        if not is_manager(request.env.user):
            return api_error('Not authorized to edit teachers.', status=403, code='forbidden')
        faculty = request.env['op.faculty'].sudo().with_context(active_test=False).browse(faculty_id)
        if not faculty.exists():
            return api_error('Teacher not found.', status=404, code='not_found')
        payload = json_body() or {}
        vals, contact, error = _teacher_vals(payload, faculty)
        if error:
            return error
        blocks, error = _security_blocks(payload, teacher=True)
        if error:
            return error
        if vals.get('email') and _email_taken(vals['email'], faculty.partner_id):
            return _email_taken_error()

        def write():
            if vals:
                faculty.write(vals)
            _apply_emergency_contact(faculty, contact)
            return _apply_security(faculty, blocks)

        delivery, error = transaction(write)
        if error:
            return error
        return api_response(_with_credentials(_teacher_detail(faculty), faculty, delivery))

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

    @http.route('/api/v1/parents/<int:parent_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_parent(self, parent_id, **kwargs):
        if not _can_list_students(request.env.user):
            return api_error('Not authorized for this parent.', status=403, code='forbidden')
        parent = request.env['op.parent'].sudo().with_context(active_test=False).browse(parent_id)
        if not parent.exists():
            return api_error('Parent not found.', status=404, code='not_found')
        return api_response(_parent_detail(parent))

    @http.route('/api/v1/parents/<int:parent_id>/photo', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def parent_photo(self, parent_id, **kwargs):
        if not _can_list_students(request.env.user):
            return api_error('Not authorized for this parent.', status=403, code='forbidden')
        parent = request.env['op.parent'].sudo().with_context(active_test=False).browse(parent_id)
        if not parent.exists():
            return api_error('Parent not found.', status=404, code='not_found')
        return _image_response(parent.name.image_512, f'parent-{parent.id}.png')

    @http.route('/api/v1/parents', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_parent(self, **kwargs):
        """{"name", "mobile", "email"?, "relationship_id", "student_ids",
        "image"?, "status"?, "account": {"username", "password", "active"?,
        "send_credentials"?, "channel"?}}: a parent record linked to their
        children, with the portal login they use for the app. Every update
        field is accepted too."""
        if not is_manager(request.env.user):
            return api_error('Not authorized to add parents.', status=403, code='forbidden')
        payload = json_body() or {}
        for required in ('name', 'mobile', 'relationship_id', 'student_ids'):
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        vals, partner_vals, documents, error = _parent_vals(payload)
        if error:
            return error
        blocks, error = _security_blocks(payload)
        if error:
            return error
        error = _require_login(blocks)
        if error:
            return error

        def create():
            partner = request.env['res.partner'].sudo().create(dict(partner_vals, is_parent=True))
            parent = request.env['op.parent'].sudo().create(dict(vals, name=partner.id))
            apply_document_sets(parent, documents)
            return parent, _apply_security(parent, blocks)

        result, error = transaction(create)
        if error:
            return error
        parent, delivery = result
        return api_response(_with_credentials(_parent_detail(parent), parent, delivery), status=201)

    @http.route('/api/v1/parents/<int:parent_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_parent(self, parent_id, **kwargs):
        """Any of the create fields (people_fields.PARENT_SPEC, plus "name",
        "image", "status", "student_ids", "address", "rte": {"category",
        "annual_income", "bpl_number", "bpl_list_type",
        "income_certificate_financial_year", "income_certificate",
        "category_certificate"}, "documents": {"additional"} and the Account &
        Security blocks). A new email or mobile is also set on the parent's
        contact, where login credentials are sent."""
        if not is_manager(request.env.user):
            return api_error('Not authorized to edit parents.', status=403, code='forbidden')
        parent = request.env['op.parent'].sudo().with_context(active_test=False).browse(parent_id)
        if not parent.exists():
            return api_error('Parent not found.', status=404, code='not_found')
        payload = json_body() or {}
        vals, partner_vals, documents, error = _parent_vals(payload)
        if error:
            return error
        blocks, error = _security_blocks(payload)
        if error:
            return error

        def write():
            if vals:
                parent.write(vals)
            if partner_vals:
                parent.name.write(partner_vals)
            apply_document_sets(parent, documents)
            return _apply_security(parent, blocks)

        delivery, error = transaction(write)
        if error:
            return error
        return api_response(_with_credentials(_parent_detail(parent), parent, delivery))
