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

Students follow the app's Add New Student screen: a single "name", the
address as one line of text, "admission_number", "parent" to link or add
a parent, an automatic login (the email, with a one-time password) and
"draft": true for "Save Draft" - drafts are kept archived, with no
enrolment and no login, until completed or discarded. Every student
response carries "profile_completion".
"""
import base64
import binascii
import re

from psycopg2 import IntegrityError

from odoo.exceptions import UserError
from odoo.tools.mimetypes import guess_mimetype

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
    DOCUMENT_SETS, PARENT_CREATE_REQUIRED, PARENT_SPEC, REQUIRED, STUDENT_CREATE_REQUIRED, STUDENT_SPEC, TEACHER_ADDRESSES, TEACHER_SPEC, WEEKDAYS, address_dict,
    apply_document_sets, documents_dict, emergency_contact_dict, fields_dict, health_dict, parse_address,
    parse_available_days, parse_document_sets, parse_fields, parse_health, parse_rte, parse_teacher_addresses,
    parse_teacher_documents, rte_dict,
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


def _image_value(payload, max_bytes=None):
    """(vals, error): {'image_1920': base64 or False} when the payload has
    an "image" key; a JPG/PNG picture of at most `max_bytes` when given."""
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
        content = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None, api_error('image must be a base64 string.', status=400, code='invalid_image')
    mimetype = guess_mimetype(content)
    if not mimetype.startswith('image/') or mimetype == 'image/svg+xml':
        # The profile photo is shown as a picture: a PDF cannot be one.
        return None, api_error('image must be a JPG or PNG picture.', status=400, code='invalid_image')
    if max_bytes and len(content) > max_bytes:
        return None, api_error('The photo must be %s MB or smaller.' % (max_bytes // (1024 * 1024)), status=413,
                               code='photo_too_large')
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


def _student_image_builder(Model, payload):
    return _image_value(payload, STUDENT_PHOTO_MAX_BYTES)


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
    "phone", "relation" (teachers)} and/or "emergency_contact_phone" (the
    screens' single "Emergency Contact Number" box). null / {} for
    emergency_contact removes the contact (vals); otherwise the contact is
    applied once the record is written."""
    contact = None
    if 'emergency_contact' in payload:
        raw = payload['emergency_contact']
        if not raw:
            vals = {'emergency_contact': False}
            if record is not None and 'emergency_contact_relation' in record._fields:
                vals['emergency_contact_relation'] = False
            return vals, None, None
        if not isinstance(raw, dict):
            return None, None, api_error('emergency_contact must be an object.', status=400,
                                         code='invalid_emergency_contact')
        contact = dict(raw)
    if 'emergency_contact_phone' in payload:
        phone = payload['emergency_contact_phone']
        if phone is not None and (isinstance(phone, bool) or not isinstance(phone, (str, int))):
            return None, None, api_error('emergency_contact_phone must be text.', status=400,
                                         code='invalid_emergency_contact_phone')
        contact = dict(contact or {}, phone=str(phone).strip() if phone is not None else False)
    return {}, contact, None


def _apply_emergency_contact(record, contact):
    """Create or update the emergency-contact person of a teacher or
    student. A blank name on an existing contact leaves the name as it is;
    a new contact sent without a name is named after the person."""
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
    elif name or partner_vals.get('phone'):
        partner_vals.setdefault('name', 'Emergency contact of %s' % record.name)
        record.emergency_contact = request.env['res.partner'].sudo().create(partner_vals)
    if 'relation' in contact and 'emergency_contact_relation' in record._fields:
        record.emergency_contact_relation = contact['relation'] or False


def _full_name_vals(record, vals):
    """{'name': ...} when an update changes first/middle/last name: the core
    records build the full name only on create."""
    parts = ('first_name', 'middle_name', 'last_name')
    if record is None or not any(part in vals for part in parts):
        return {}
    names = [vals[part] if part in vals else record[part] for part in parts]
    return {'name': ' '.join(filter(None, names))}


def _split_name(payload):
    """(payload, error): a single "name" ("Piyush Kumar Mathur") as
    first/middle/last name - keys sent explicitly win."""
    if 'name' not in payload:
        return payload, None
    name = payload['name']
    if _blank_text(name):
        return None, api_error('name is required.', status=400, code='missing_name')
    parts = str(name).split() if isinstance(name, str) else []
    if len(parts) < 2:
        return None, api_error('name must have a first and a last name.', status=400, code='invalid_name')
    payload = dict(payload)
    payload.setdefault('first_name', parts[0])
    payload.setdefault('middle_name', ' '.join(parts[1:-1]) or None)
    payload.setdefault('last_name', parts[-1])
    return payload, None


def _blank_text(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _teacher_code_taken(code, faculty=None):
    domain = [('teacher_code', '=ilike', code)]
    if faculty:
        domain.append(('id', '!=', faculty.id))
    return bool(request.env['op.faculty'].sudo().with_context(active_test=False).search_count(domain, limit=1))


# -- teachers -----------------------------------------------------------------------------


def _teacher_dict(faculty):
    return {
        'id': faculty.id,
        'teacher_code': faculty.teacher_code or None,
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
            'usage_percent': round(100 * faculty.weekly_period_count / faculty.max_weekly_periods)
            if faculty.max_weekly_periods else 0,
            'workload_status': faculty.workload_status,
            'timetable_auto_assign': faculty.timetable_auto_assign,
            'available_days': [day for day in WEEKDAYS if faculty['available_%s' % day]],
        },
        'responsibilities': [ref(r) for r in faculty.responsibility_ids],
        'notes': faculty.staff_notes or None,
        'permissions': {key: faculty[field] for key, field in TEACHER_PERMISSION_FIELDS.items()},
        'health': health_dict(faculty),
        'documents': [document_dict(d) for d in faculty.document_ids],
        'academic_documents': documents_dict(faculty)['academic_documents'],
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
    if 'teacher_code' in payload:
        code = payload['teacher_code']
        if _blank_text(code) or not isinstance(code, str):
            return None, None, api_error('teacher_code is required (use regenerate-code for a new one).',
                                         status=400, code='missing_teacher_code')
        if _teacher_code_taken(code.strip(), faculty):
            return None, None, api_error('This Teacher ID is already used.', status=409, code='teacher_code_taken')
    vals, error = _profile_vals(
        request.env['op.faculty'], payload, TEACHER_SPEC, _image_builder, parse_address,
        parse_teacher_addresses, parse_health, lambda Model, body: _teacher_extra_vals(Model, body, faculty))
    if error:
        return None, None, error
    extra, contact, error = _emergency_contact(payload, faculty)
    if error:
        return None, None, error
    vals.update(extra)
    vals.update(_full_name_vals(faculty, vals))
    return vals, contact, None


# -- students -----------------------------------------------------------------------------


def _current_enrollment(student):
    """The running enrolment, else the one finished last (see
    op.student._bxi_current_enrolment in bxi_people_management)."""
    return student._bxi_current_enrolment()


STUDENT_PHOTO_MAX_BYTES = 1024 * 1024

# Profile Completion of the Add New Student screen: one equal share per
# item that is filled in, worked out from the response itself.
_STUDENT_COMPLETION = (
    ('image', lambda d: d['has_photo']),
    ('name', lambda d: d.get('first_name')),
    ('gender', lambda d: d.get('gender')),
    ('birth_date', lambda d: d.get('birth_date')),
    ('email', lambda d: d.get('email')),
    ('phone', lambda d: d.get('phone')),
    ('blood_group', lambda d: d.get('blood_group')),
    ('address', lambda d: any(d['address'].values())),
    ('admission_number', lambda d: d.get('admission_number')),
    ('admission_date', lambda d: d.get('admission_date')),
    ('class', lambda d: d.get('class')),
    ('section', lambda d: d.get('section')),
    ('roll_number', lambda d: d.get('roll_number')),
    ('parent', lambda d: d.get('parents')),
    ('aadhaar_number', lambda d: (d.get('aadhaar') or {}).get('last4')),
    ('aadhaar_document', lambda d: (d.get('id_verification') or {}).get('documents')),
    ('face', lambda d: (d.get('face') or {}).get('state') in ('active', 'pending')),
    ('medical_conditions', lambda d: d.get('medical_conditions') or d['health'].get('allergy')
     or d['health'].get('chronic_conditions')),
    ('medical_records', lambda d: d['documents'].get('medical_records')),
    ('birth_certificate', lambda d: d['documents'].get('birth_certificate')),
    ('transfer_certificate', lambda d: d['documents'].get('transfer_certificate')),
    ('previous_school_certificate', lambda d: d['documents'].get('previous_school_certificate')),
)


def _profile_completion(data, checks=_STUDENT_COMPLETION):
    """{percent, label, missing} for the screens' Profile badge."""
    missing = [key for key, filled in checks if not filled(data)]
    percent = round(100 * (len(checks) - len(missing)) / len(checks))
    label = 'Just started' if percent < 25 else 'In progress' if percent < 75 else \
        'Almost done' if percent < 100 else 'Complete'
    return {'percent': percent, 'label': label, 'missing': missing}


def _student_admin_dict(student):
    data = _student_detail(student)
    current = _current_enrollment(student)
    data.update({
        'draft': bool(student.bxi_is_draft),
        'status': current.state or None,
        'department': ref(current.course_id.department_id),
        'certificate_number': student.certificate_number or None,
        'emergency_contact': emergency_contact_dict(student),
        'health': health_dict(student),
        'documents': documents_dict(student),
    })
    if student.bxi_is_draft:
        # A draft has no enrolment yet: what was chosen on the screen.
        data.update({
            'class': ref(student.bxi_draft_course_id),
            'section': ref(student.bxi_draft_batch_id),
            'roll_number': student.bxi_draft_roll_number or None,
            'status': student.bxi_draft_state or None,
            'department': ref(student.bxi_draft_course_id.department_id),
        })
    data['status_label'] = STATUS_LABELS.get(data['status'])
    for key, value in fields_dict(student, STUDENT_SPEC).items():
        data.setdefault(key, value)
    data.update(security_dict(student))
    data['profile_completion'] = _profile_completion(data)
    return data


def _split_student_name(payload):
    """(payload, error): the screen's single "Full Name" as first/middle/
    last name - keys sent explicitly win. One word is a first name only."""
    if 'name' not in payload:
        return payload, None
    name = payload['name']
    if _blank_text(name):
        return None, api_error('name is required.', status=400, code='missing_name')
    if not isinstance(name, str):
        return None, api_error('name must be text.', status=400, code='invalid_name')
    parts = name.split()
    payload = dict(payload)
    payload.setdefault('first_name', parts[0])
    payload.setdefault('middle_name', ' '.join(parts[1:-1]) or None)
    payload.setdefault('last_name', parts[-1] if len(parts) > 1 else None)
    return payload, None


def _address_given(address):
    if isinstance(address, str):
        return bool(address.strip())
    return isinstance(address, dict) and any(not _blank_text(value) for value in address.values())


def _missing_create_field(payload):
    """The first starred field of the Add New Student screen missing from
    a create body, or None."""
    for key in REQUIRED['op.student'] + STUDENT_CREATE_REQUIRED:
        if _blank_text(payload.get(key)):
            return key
    if not _address_given(payload.get('address')):
        return 'address'
    if not payload.get('parent') and not payload.get('parent_ids'):
        return 'parent'
    return None


def _check_complete(student):
    """Raise PeopleError for the first starred field a draft being
    completed still lacks (class and section are checked by the
    enrolment)."""
    student = student.sudo()
    for key, value in (
        ('first_name', student.first_name), ('gender', student.gender), ('email', student.email),
        ('birth_date', student.birth_date), ('phone', student.phone), ('admission_number', student.gr_no),
        ('admission_date', student.admission_date),
        ('address', student.street or student.street2 or student.city), ('parent', student.parent_ids),
    ):
        if not value:
            raise PeopleError('%s is required to complete the draft.' % key, 'missing_%s' % key)


def _admission_number_error(number, student=None):
    """409 when another student (drafts included) has this admission
    number - the core keeps it unique."""
    if not number:
        return None
    domain = [('gr_no', '=', number)]
    if student:
        domain.append(('id', '!=', student.id))
    if request.env['op.student'].sudo().with_context(active_test=False).search_count(domain, limit=1):
        return api_error('Another student already has this admission number.', status=409,
                         code='admission_number_taken')
    return None


def _parse_draft(payload):
    """(True / False / None when absent, error)."""
    if 'draft' not in payload:
        return None, None
    if not isinstance(payload['draft'], bool):
        return None, api_error('draft must be true or false.', status=400, code='invalid_draft')
    return payload['draft'], None


def _check_draft_blocks(blocks):
    """A draft has no login yet: no account, face or ID review."""
    for key in ('account', 'face', 'id_verification'):
        if blocks[key] is not None:
            return api_error('%s is not allowed on a draft: complete the student first.' % key, status=400,
                             code='not_allowed_in_draft')
    return None


# The screen's Status words for the enrolment state.
STATUS_ALIASES = {'active': 'running', 'inactive': 'finished'}
STATUS_LABELS = {'running': 'Active', 'finished': 'Inactive'}


def _check_status(status):
    """(enrolment state, error) for a "status" value: running | finished,
    or the screen's active | inactive."""
    status = STATUS_ALIASES.get(status, status) if isinstance(status, str) else status
    error = check_selection(request.env['op.student.course'], 'state', status, key='status')
    return (None, error) if error else (status, None)


def _enrollment_state(payload):
    """(state or None, error): "status", or "enrollment.status", for a new
    enrolment."""
    enrollment = payload.get('enrollment') if isinstance(payload.get('enrollment'), dict) else {}
    status = payload.get('status') or enrollment.get('status')
    if not status:
        return None, None
    return _check_status(status)


def _draft_enrollment_vals(payload):
    """(vals, error): a draft's chosen class / section / roll number /
    status, kept on the student until the enrolment is created."""
    vals = {}
    if 'enrollment' in payload and payload['enrollment'] is not None:
        enrollment = payload['enrollment']
        if not isinstance(enrollment, dict):
            return None, api_error('enrollment must be an object.', status=400, code='invalid_enrollment')
        records = {}
        for key, field, model in (('course_id', 'bxi_draft_course_id', 'op.course'),
                                  ('batch_id', 'bxi_draft_batch_id', 'op.batch')):
            if key in enrollment:
                records[key], error = resolve_record(request.env, model, enrollment[key], key)
                if error:
                    return None, error
                vals[field] = records[key].id or False
        if records.get('course_id') and records.get('batch_id') and \
                records['batch_id'].course_id != records['course_id']:
            return None, api_error('This section does not belong to that class.', status=400,
                                   code='batch_course_mismatch')
        if 'roll_number' in enrollment:
            vals['bxi_draft_roll_number'] = str(enrollment['roll_number'] or '').strip() or False
    state, error = _enrollment_state(payload)
    if error:
        return None, error
    if state:
        vals['bxi_draft_state'] = state
    return vals, None


def _draft_enrollment(student):
    """The enrolment body of a draft being completed, from what it kept."""
    return {
        'course_id': student.bxi_draft_course_id.id, 'batch_id': student.bxi_draft_batch_id.id,
        'roll_number': student.bxi_draft_roll_number,
    }


def _parent_with_mobile(mobile):
    """An existing parent whose mobile is the same number (spaces, dashes
    and the +91 prefix ignored)."""
    digits = re.sub(r'\D', '', mobile)[-10:]
    if len(digits) < 4:
        return request.env['op.parent']
    candidates = request.env['op.parent'].sudo().with_context(active_test=False).search(
        [('mobile', 'ilike', digits[-4:])])
    return candidates.filtered(lambda p: re.sub(r'\D', '', p.mobile or '')[-10:] == digits)[:1]


def _parent_exists_error(existing):
    return request.make_json_response({'success': False, 'error': {
        'message': 'A parent with this phone number already exists (%s): link them instead.' % existing.name.name,
        'code': 'parent_exists', 'existing_parent_id': existing.id}}, status=409)


def _parent_detail_vals(block):
    """(vals, error) for the parent details sent in a "parent" block:
    {name?, relationship_id?, mobile?, email?}."""
    vals = {}
    for key in ('name', 'mobile'):
        if key in block:
            if _blank_text(block[key]):
                return None, api_error('parent.%s is required.' % key, status=400, code='missing_parent_%s' % key)
            vals[key] = str(block[key]).strip()
    if 'relationship_id' in block:
        if _blank_text(block['relationship_id']):
            return None, api_error('parent.relationship_id is required.', status=400,
                                   code='missing_parent_relationship_id')
        relationship, error = resolve_record(request.env, 'op.parent.relationship', block['relationship_id'],
                                             'relationship_id')
        if error:
            return None, error
        vals['relationship_id'] = relationship.id
    if 'email' in block:
        vals['email'] = str(block['email'] or '').strip() or False
    return vals, None


def _parse_student_parent(payload, student=None):
    """(parsed or None, error) for the screen's Parent Linking "parent"
    block:
      {"parent_id", <details>?}   link that parent (and correct its details)
      {"name", "relationship_id", "mobile", "email"?}
                                  add a new parent - or, when a parent
                                  already linked to this student has that
                                  mobile, correct that parent's details
      "replace_parent_id"?        unlink that parent of this student (the
                                  screen's single parent slot changing)
    A mobile that belongs to another, unlinked parent answers 409
    parent_exists with its id, so the app can offer to link them."""
    block = payload.get('parent')
    if block is None:
        return None, None
    if not isinstance(block, dict):
        return None, api_error('parent must be an object.', status=400, code='invalid_parent')
    linked = student.parent_ids if student else request.env['op.parent']
    parsed = {'replace': request.env['op.parent']}
    if block.get('replace_parent_id'):
        old, error = resolve_record(request.env, 'op.parent', block['replace_parent_id'], 'replace_parent_id')
        if error:
            return None, error
        if old not in linked:
            return None, api_error('replace_parent_id is not a parent of this student.', status=400,
                                   code='invalid_replace_parent_id')
        parsed['replace'] = old
    details, error = _parent_detail_vals(block)
    if error:
        return None, error
    if block.get('parent_id'):
        parent, error = resolve_record(request.env, 'op.parent', block['parent_id'], 'parent_id')
        if error:
            return None, error
    else:
        for key in ('name', 'relationship_id', 'mobile'):
            if key not in details:
                return None, api_error('parent.%s is required.' % key, status=400, code='missing_parent_%s' % key)
        parent = _parent_with_mobile(details['mobile'])
        if parent and parent not in linked:
            return None, _parent_exists_error(parent)
    if parent and details.get('mobile'):
        # A changed mobile must not be another parent's.
        other = _parent_with_mobile(details['mobile'])
        if other and other != parent:
            return None, _parent_exists_error(other)
    if parent and parent == parsed['replace']:
        parsed['replace'] = request.env['op.parent']
    parsed.update(parent=parent, details=details)
    return parsed, None


def _apply_student_parent(student, parsed):
    if not parsed:
        return
    parent, details = parsed['parent'], parsed['details']
    if parsed['replace']:
        student.write({'parent_ids': [(3, parsed['replace'].id)]})
    if not parent:
        partner = request.env['res.partner'].sudo().create({
            'name': details['name'], 'phone': details['mobile'], 'email': details.get('email') or False,
            'is_parent': True})
        request.env['op.parent'].sudo().create({
            'name': partner.id, 'mobile': details['mobile'], 'email': details.get('email') or False,
            'relationship_id': details['relationship_id'], 'student_ids': [(4, student.id)]})
        return
    parent = parent.sudo()
    if parent not in student.parent_ids:
        student.write({'parent_ids': [(4, parent.id)]})
    parent_vals = {key: details[key] for key in ('mobile', 'email', 'relationship_id') if key in details}
    partner_vals = {'name': details['name']} if 'name' in details else {}
    if 'mobile' in details:
        partner_vals['phone'] = details['mobile']
    if 'email' in details:
        partner_vals['email'] = details['email']
    if parent_vals:
        parent.write(parent_vals)
    if partner_vals:
        parent.name.write(partner_vals)


def _student_vals(payload, student=None):
    """(vals, emergency_contact, document_sets, error) for a student create
    (student=None) or update."""
    Student = request.env['op.student']
    vals, error = _profile_vals(Student, payload, STUDENT_SPEC, _student_image_builder, parse_address,
                                parse_health)
    if error:
        return None, None, None, error
    extra, contact, error = _emergency_contact(payload, student)
    if error:
        return None, None, None, error
    vals.update(extra)
    vals.update(_full_name_vals(student, vals))
    if vals.get('library_card_id'):
        card = request.env['op.library.card'].sudo().browse(vals['library_card_id'])
        if card.type != 'student':
            return None, None, None, api_error('library_card_id must be a student library card.', status=400,
                                               code='invalid_library_card_id')
        if card.student_id and card.student_id != student:
            return None, None, None, api_error('This library card belongs to another student.', status=409,
                                               code='library_card_taken')
    documents, error = parse_document_sets('op.student', payload)
    if error:
        return None, None, None, error
    return vals, contact, documents, None


def _sync_library_card(student, vals):
    """The card's own Student follows the student's Library Card."""
    card = student.library_card_id
    if vals.get('library_card_id') and card.student_id != student:
        card.write({'student_id': student.id, 'partner_id': student.partner_id.id})


def _enrollment_line(enrollment, state=None):
    """(op.student.course vals, error) for a new student's enrolment: class
    and section are required (the roll number is optional), and the
    section must belong to the class."""
    if not isinstance(enrollment, dict):
        return None, api_error('enrollment is required.', status=400, code='missing_enrollment')
    for key in ('course_id', 'batch_id'):
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
    line = {'course_id': course.id, 'batch_id': batch.id,
            'roll_number': str(enrollment.get('roll_number') or '').strip() or False}
    if state:
        line['state'] = state
    if enrollment.get('academic_year_id'):
        year, error = resolve_record(request.env, 'op.academic.year', enrollment['academic_year_id'],
                                     'academic_year_id')
        if error:
            return None, error
        line['academic_years_id'] = year.id
    return line, None


def _change_enrollment(student, enrollment):
    """The Edit Student screen's Class / Section / Roll Number ("enrollment"
    on update): the same section only changes the roll number (blank clears
    it); another section is a transfer (see _transfer)."""
    if not isinstance(enrollment, dict):
        return api_error('enrollment must be an object.', status=400, code='invalid_enrollment')
    current = running_enrollment(student)
    batch_id = enrollment.get('batch_id') or current.batch_id.id
    if not batch_id:
        return api_error('enrollment.batch_id is required.', status=400, code='missing_batch_id')
    same_course = not enrollment.get('course_id') or parse_int(enrollment['course_id'], 'course_id')[0] == \
        current.course_id.id
    if current and parse_int(batch_id, 'batch_id')[0] == current.batch_id.id and same_course:
        if 'roll_number' in enrollment:
            current.roll_number = str(enrollment['roll_number'] or '').strip() or False
        return None
    return _transfer(student, {key: enrollment.get(key) for key in ('batch_id', 'course_id', 'roll_number')
                               if enrollment.get(key)} | {'batch_id': batch_id})


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


def _discard(record, model, partner):
    """Delete a draft with its own files, then its contact - kept archived
    when something else still uses it (a message, a log)."""
    attachments = request.env['ir.attachment'].sudo()
    for field in DOCUMENT_SETS[model].values():
        attachments |= record[field]
    attachments |= record.id_document_ids
    attachments.filtered(lambda a: a.res_model == model and a.res_id == record.id).unlink()
    record.unlink()
    try:
        with request.env.cr.savepoint():
            partner.unlink()
    except (UserError, IntegrityError):
        partner.active = False


def _student_record(student_id):
    student = request.env['op.student'].sudo().with_context(active_test=False).browse(student_id)
    return student if student.exists() else None


# -- parents ------------------------------------------------------------------------------


_PARENT_COMPLETION = (
    ('image', lambda d: d['has_photo']),
    ('name', lambda d: d.get('name')),
    ('gender', lambda d: d.get('gender')),
    ('birth_date', lambda d: d.get('birth_date')),
    ('email', lambda d: d.get('email')),
    ('phone', lambda d: d.get('phone')),
    ('address', lambda d: any(d['address'].values())),
    ('relationship', lambda d: d.get('relationship')),
    ('students', lambda d: d.get('students')),
    ('aadhaar_card', lambda d: d['documents'].get('aadhaar_card')),
    ('pan_card', lambda d: d['documents'].get('pan_card')),
    ('id_proof', lambda d: d['documents'].get('id_proof')),
)


def _linked_student(student):
    """A Linked Students row: name, admission number, class and section."""
    line = student._bxi_current_enrolment()
    return {
        'id': student.id, 'name': student.name, 'admission_number': student.gr_no or None,
        'class': ref(line.course_id), 'section': ref(line.batch_id), 'roll_number': line.roll_number or None,
    }


def _parent_dict(parent):
    enrollments = parent.student_ids.course_detail_ids.filtered(lambda line: line.state == 'running')
    return {
        'id': parent.id,
        'name': parent.name.name,
        'email': parent.email or parent.name.email or None,
        'mobile': parent.mobile or None,
        'phone': parent.mobile or None,
        'relationship': ref(parent.relationship_id),
        'draft': bool(parent.bxi_is_draft),
        'students': [_linked_student(s) for s in parent.student_ids],
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
    data['profile_completion'] = _profile_completion(data, _PARENT_COMPLETION)
    return data


def _parent_record(parent_id):
    parent = request.env['op.parent'].sudo().with_context(active_test=False).browse(parent_id)
    return parent if parent.exists() else None


def _parent_mobile(payload):
    """The mobile a parent body sends, as "mobile" or "phone"."""
    for key in ('phone', 'mobile'):
        if not _blank_text(payload.get(key)):
            return str(payload[key]).strip()
    return None


def _missing_parent_field(payload):
    """The first starred field of the Add Parent screen missing from a
    create body, or None."""
    if _blank_text(payload.get('name')):
        return 'name'
    if not _parent_mobile(payload):
        return 'mobile'
    for key in PARENT_CREATE_REQUIRED:
        if _blank_text(payload.get(key)):
            return key
    if not _address_given(payload.get('address')):
        return 'address'
    for key in ('relationship_id', 'student_ids'):
        if not payload.get(key):
            return key
    return None


def _check_parent_complete(parent):
    """Raise PeopleError for the first starred field a parent draft being
    completed still lacks."""
    parent = parent.sudo()
    for key, value in (
        ('mobile', parent.mobile), ('gender', parent.gender), ('birth_date', parent.birth_date),
        ('email', parent.email or parent.name.email), ('address', parent.street or parent.street2 or parent.city),
        ('relationship_id', parent.relationship_id), ('student_ids', parent.student_ids),
    ):
        if not value:
            raise PeopleError('%s is required to complete the draft.' % key, 'missing_%s' % key)


def _parent_mobile_error(payload, parent=None):
    """409 parent_exists when the mobile sent is another parent's."""
    mobile = _parent_mobile(payload)
    if not mobile:
        return None
    existing = _parent_with_mobile(mobile)
    if existing and existing != parent:
        return _parent_exists_error(existing)
    return None


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
    if 'phone' in payload and _blank_text(payload['phone']) and not _blank_text(payload.get('mobile')):
        # "phone" is the screen's name for the mobile: an empty one next
        # to a mobile changes nothing.
        payload = {key: value for key, value in payload.items() if key != 'phone'}
    vals, error = _profile_vals(request.env['op.parent'], payload, PARENT_SPEC, parse_address, parse_rte,
                                _parent_status, _parent_students)
    if error:
        return None, None, None, error
    partner_vals, error = _image_value(payload, STUDENT_PHOTO_MAX_BYTES)
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
    def list_students(self, q=None, course_id=None, batch_id=None, draft=None, **kwargs):
        """Office staff: every student. Teachers: the sections they teach.
        ?draft=true: office staff only, the drafts saved with "Save Draft"
        (left out of the normal list)."""
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = []
        Student = request.env['op.student'].sudo()
        if draft in ('1', 'true', 'True'):
            if not _can_list_students(request.env.user):
                return api_error('Not authorized to list drafts.', status=403, code='forbidden')
            Student = Student.with_context(active_test=False)
            domain.append(('bxi_is_draft', '=', True))
        elif not _can_list_students(request.env.user):
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
        total = Student.search_count(domain)
        students = Student.search(domain, limit=limit, offset=offset, order='name')
        return api_response({'students': [student_summary(s) for s in students]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/students', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_student(self, **kwargs):
        """The office's Add New Student screen: {"name" (or "first_name",
        "middle_name"?, "last_name"?), "gender", "birth_date", "email",
        "phone", "address" (text or object), "admission_number",
        "admission_date", "enrollment": {"course_id", "batch_id",
        "roll_number"?}, "status"?, "parent": {"parent_id"} | {"name",
        "relationship_id", "mobile"} (or "parent_ids"), "image"?, ...} plus
        every update field. Without "account" the login is the student's
        email with a one-time password, returned once as "credentials".

        "draft": true saves the screen as it is ("Save Draft"): only the
        name is required, nothing is enrolled and no login is made until
        the draft is completed with /students/<id>/update {"draft": false}."""
        if not is_manager(request.env.user):
            return api_error('Not authorized to add students.', status=403, code='forbidden')
        payload, error = _split_student_name(json_body() or {})
        if error:
            return error
        draft, error = _parse_draft(payload)
        if error:
            return error
        if draft:
            if _blank_text(payload.get('first_name')):
                return api_error('name is required.', status=400, code='missing_name')
        else:
            missing = _missing_create_field(payload)
            if missing:
                return api_error(f'{missing} is required.', status=400, code=f'missing_{missing}')
        vals, contact, documents, error = _student_vals(payload)
        if error:
            return error
        parent, error = _parse_student_parent(payload)
        if error:
            return error
        blocks, error = _security_blocks(payload)
        if error:
            return error
        if draft:
            error = _check_draft_blocks(blocks)
            if error:
                return error
            extra, error = _draft_enrollment_vals(payload)
            if error:
                return error
            vals.update(extra, bxi_is_draft=True, active=False)
        else:
            state, error = _enrollment_state(payload)
            if error:
                return error
            line, error = _enrollment_line(payload.get('enrollment'), state)
            if error:
                return error
            vals['course_detail_ids'] = [(0, 0, line)]
            blocks['account'] = dict(blocks['account'] or {}, create_login=True)
        if _email_taken(payload.get('email')):
            return _email_taken_error()
        error = _admission_number_error(vals.get('gr_no'))
        if error:
            return error

        def create():
            student = request.env['op.student'].sudo().create(vals)
            _sync_library_card(student, vals)
            _apply_emergency_contact(student, contact)
            apply_document_sets(student, documents)
            _apply_student_parent(student, parent)
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
        """The Edit Student screen. Any of the create fields
        (people_fields.STUDENT_SPEC, plus "name", "image", "address",
        "health", "emergency_contact": {"name", "phone"}, "parent" (see
        _parse_student_parent: link, add, correct or replace a parent),
        "documents": {"birth_certificate", "transfer_certificate",
        "previous_school_certificate", "medical_records"} and the Account &
        Security blocks), plus "enrollment": {"course_id"?, "batch_id"?,
        "roll_number"?} - the same section changes only the roll number,
        another one moves the student there ("transfer" is the older name
        of the same thing) - and "status": running | finished (or active |
        inactive) for the current enrolment. Only the keys sent are changed;
        "draft": true on a student already saved is an ordinary save.

        On a draft: the same keys plus "enrollment" (the class / section /
        roll number it keeps); "draft": false completes it - every starred
        field must then be filled in, and the enrolment and login are
        created."""
        if not is_manager(request.env.user):
            return api_error('Not authorized to edit students.', status=403, code='forbidden')
        student = _student_record(student_id)
        if not student:
            return api_error('Student not found.', status=404, code='not_found')
        payload, error = _split_student_name(json_body() or {})
        if error:
            return error
        draft, error = _parse_draft(payload)
        if error:
            return error
        is_draft = student.bxi_is_draft
        # "Save Draft" on the Edit screen of a saved student just saves.
        complete = is_draft and draft is False
        vals, contact, documents, error = _student_vals(payload, student)
        if error:
            return error
        if vals.get('email') and _email_taken(vals['email'], student.partner_id):
            return _email_taken_error()
        error = _admission_number_error(vals.get('gr_no'), student)
        if error:
            return error
        parent, error = _parse_student_parent(payload, student)
        if error:
            return error
        blocks, error = _security_blocks(payload)
        if error:
            return error
        status = None
        enrollment = None
        if is_draft:
            if 'transfer' in payload:
                return api_error('A draft has no enrolment to transfer: complete it first.', status=400,
                                 code='student_is_draft')
            if not complete:
                error = _check_draft_blocks(blocks)
                if error:
                    return error
            # Completing the draft is what makes it active.
            vals.pop('active', None)
            extra, error = _draft_enrollment_vals(payload)
            if error:
                return error
            vals.update(extra)
        else:
            if 'transfer' in payload and payload.get('enrollment') is not None:
                return api_error('Send either enrollment or transfer, not both.', status=400,
                                 code='invalid_enrollment')
            if payload.get('enrollment') is not None:
                enrollment = payload['enrollment']
            if 'status' in payload or isinstance(enrollment, dict) and 'status' in enrollment:
                raw = payload['status'] if 'status' in payload else enrollment['status']
                status, error = _check_status(raw)
                if error:
                    return error
        if complete:
            blocks['account'] = dict(blocks['account'] or {}, create_login=True)

        def apply():
            if vals:
                student.write(vals)
            _sync_library_card(student, vals)
            _apply_emergency_contact(student, contact)
            apply_document_sets(student, documents)
            _apply_student_parent(student, parent)
            if complete:
                _check_complete(student)
                line, error = _enrollment_line(_draft_enrollment(student), student.bxi_draft_state)
                if error:
                    raise PeopleError(None, None, response=error)
                student.write({
                    'course_detail_ids': [(0, 0, line)], 'active': True, 'bxi_is_draft': False,
                    'bxi_draft_course_id': False, 'bxi_draft_batch_id': False, 'bxi_draft_roll_number': False,
                    'bxi_draft_state': False,
                })
            if 'transfer' in payload or enrollment is not None:
                error = _transfer(student, payload['transfer']) if 'transfer' in payload else \
                    _change_enrollment(student, enrollment)
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

    @http.route('/api/v1/students/<int:student_id>/discard', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def discard_student_draft(self, student_id, **kwargs):
        """Delete a draft saved with "Save Draft", with its files. Students
        that were completed cannot be deleted here."""
        if not is_manager(request.env.user):
            return api_error('Not authorized to edit students.', status=403, code='forbidden')
        student = _student_record(student_id)
        if not student:
            return api_error('Student not found.', status=404, code='not_found')
        if not student.bxi_is_draft:
            return api_error('Only a draft can be discarded.', status=400, code='not_a_draft')

        def discard():
            _discard(student, 'op.student', student.partner_id)
            return True

        _result, error = transaction(discard)
        if error:
            return error
        return api_response({'id': student_id, 'discarded': True})

    @http.route(['/api/v1/<any("students", "parents"):kind>/<int:record_id>/documents/<int:attachment_id>',
                 '/api/v1/<any("teachers"):kind>/<int:record_id>/academic-documents/<int:attachment_id>'],
                type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def person_document(self, kind, record_id, attachment_id, **kwargs):
        """Download one file of a student's or parent's "documents" sets, or
        of a teacher's "academic_documents"."""
        if not _can_list_students(request.env.user):
            return api_error('Not authorized for these documents.', status=403, code='forbidden')
        model = {'students': 'op.student', 'parents': 'op.parent', 'teachers': 'op.faculty'}[kind]
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
        domain = ['|', ('name', 'ilike', q), ('teacher_code', 'ilike', q)] if q else []
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
        payload, error = _split_name(json_body() or {})
        if error:
            return error
        for required in REQUIRED['op.faculty']:
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        vals, contact, error = _teacher_vals(payload)
        if error:
            return error
        blocks, error = _security_blocks(payload, teacher=True)
        if error:
            return error
        documents, error = parse_teacher_documents(payload)
        if error:
            return error
        if _email_taken(vals.get('email')):
            return _email_taken_error()

        def create():
            faculty = request.env['op.faculty'].sudo().create(vals)
            _apply_emergency_contact(faculty, contact)
            apply_document_sets(faculty, documents)
            return faculty, _apply_security(faculty, blocks)

        result, error = transaction(create)
        if error:
            return error
        faculty, delivery = result
        return api_response(_with_credentials(_teacher_detail(faculty), faculty, delivery), status=201)

    @http.route('/api/v1/teachers/<int:faculty_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_teacher(self, faculty_id, **kwargs):
        """Any of the create fields (people_fields.TEACHER_SPEC, plus "name"
        (split into first/middle/last), "image", "emergency_contact_phone",
        "address", "official_address", "postal_address", "regional_address",
        "health", "emergency_contact", "subject_ids",
        "specialization_subject_id", "designation_id", "responsibility_ids",
        "status", "notes", "assignments", "permissions", "workload":
        {"max_weekly_periods", "timetable_auto_assign", "available_days"},
        "documents", "academic_documents", "employee_id" and the Account &
        Security blocks); only the keys sent are changed."""
        if not is_manager(request.env.user):
            return api_error('Not authorized to edit teachers.', status=403, code='forbidden')
        faculty = request.env['op.faculty'].sudo().with_context(active_test=False).browse(faculty_id)
        if not faculty.exists():
            return api_error('Teacher not found.', status=404, code='not_found')
        payload, error = _split_name(json_body() or {})
        if error:
            return error
        vals, contact, error = _teacher_vals(payload, faculty)
        if error:
            return error
        blocks, error = _security_blocks(payload, teacher=True)
        if error:
            return error
        documents, error = parse_teacher_documents(payload)
        if error:
            return error
        if vals.get('email') and _email_taken(vals['email'], faculty.partner_id):
            return _email_taken_error()

        def write():
            if vals:
                faculty.write(vals)
            _apply_emergency_contact(faculty, contact)
            apply_document_sets(faculty, documents)
            return _apply_security(faculty, blocks)

        delivery, error = transaction(write)
        if error:
            return error
        return api_response(_with_credentials(_teacher_detail(faculty), faculty, delivery))

    @http.route('/api/v1/teachers/<int:faculty_id>/regenerate-code', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def regenerate_teacher_code(self, faculty_id, **kwargs):
        """Give the teacher the next free Teacher ID (T-0001...)."""
        if not is_manager(request.env.user):
            return api_error('Not authorized to edit teachers.', status=403, code='forbidden')
        faculty = request.env['op.faculty'].sudo().with_context(active_test=False).browse(faculty_id)
        if not faculty.exists():
            return api_error('Teacher not found.', status=404, code='not_found')
        faculty.action_regenerate_teacher_code()
        return api_response(_teacher_detail(faculty))

    # -- parents ------------------------------------------------------------------

    @http.route('/api/v1/parents', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_parents(self, q=None, student_id=None, draft=None, **kwargs):
        """?draft=true: the drafts saved with "Save Draft" (left out of the
        normal list)."""
        if not _can_list_students(request.env.user):
            return api_error('Not authorized to list parents.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = []
        Parent = request.env['op.parent'].sudo()
        if draft in ('1', 'true', 'True'):
            Parent = Parent.with_context(active_test=False)
            domain.append(('bxi_is_draft', '=', True))
        if q:
            domain += ['|', '|', ('name.name', 'ilike', q), ('mobile', 'ilike', q), ('email', 'ilike', q)]
        if student_id:
            student_id, error = parse_int(student_id, 'student_id')
            if error:
                return error
            domain.append(('student_ids', 'in', student_id))
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
        """The office's Add Parent screen: {"name", "gender", "birth_date",
        "email", "phone" (or "mobile"), "address" (text or object),
        "relationship_id", "student_ids", "image"? (JPG/PNG, max 1 MB),
        "documents"?: {"aadhaar_card", "pan_card", "id_proof",
        "additional"} (max 5 MB each), "status"?, ...} plus every update
        field. A mobile that is already a parent's answers 409
        parent_exists with its id. Without "account" the login is the
        parent's email with a one-time password, returned once as
        "credentials".

        "draft": true saves the screen as it is ("Save Draft"): only the
        name is required and no login is made until the draft is completed
        with /parents/<id>/update {"draft": false}."""
        if not is_manager(request.env.user):
            return api_error('Not authorized to add parents.', status=403, code='forbidden')
        payload = json_body() or {}
        draft, error = _parse_draft(payload)
        if error:
            return error
        if draft:
            if _blank_text(payload.get('name')):
                return api_error('name is required.', status=400, code='missing_name')
        else:
            missing = _missing_parent_field(payload)
            if missing:
                return api_error(f'{missing} is required.', status=400, code=f'missing_{missing}')
        vals, partner_vals, documents, error = _parent_vals(payload)
        if error:
            return error
        error = _parent_mobile_error(payload)
        if error:
            return error
        blocks, error = _security_blocks(payload)
        if error:
            return error
        if draft:
            error = _check_draft_blocks(blocks)
            if error:
                return error
            vals.update(bxi_is_draft=True, active=False)
        else:
            blocks['account'] = dict(blocks['account'] or {}, create_login=True)

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
        """The Edit Parent screen. Any of the create fields
        (people_fields.PARENT_SPEC, plus "name", "image", "status",
        "student_ids" (the whole list - add one to link a new student),
        "address", "rte": {"category", "annual_income", "bpl_number",
        "bpl_list_type", "income_certificate_financial_year",
        "income_certificate", "category_certificate"}, "documents":
        {"aadhaar_card", "pan_card", "id_proof", "additional"} and the
        Account & Security blocks). A new email or mobile is also set on the
        parent's contact, where login credentials are sent.

        On a draft: "draft": false completes it - every starred field must
        then be filled in, and the login is created. "draft": true on a
        parent already saved is an ordinary save."""
        if not is_manager(request.env.user):
            return api_error('Not authorized to edit parents.', status=403, code='forbidden')
        parent = _parent_record(parent_id)
        if not parent:
            return api_error('Parent not found.', status=404, code='not_found')
        payload = json_body() or {}
        draft, error = _parse_draft(payload)
        if error:
            return error
        is_draft = parent.bxi_is_draft
        complete = is_draft and draft is False
        vals, partner_vals, documents, error = _parent_vals(payload)
        if error:
            return error
        error = _parent_mobile_error(payload, parent)
        if error:
            return error
        blocks, error = _security_blocks(payload)
        if error:
            return error
        if is_draft:
            if not complete:
                error = _check_draft_blocks(blocks)
                if error:
                    return error
            # Completing the draft is what makes it active.
            vals.pop('active', None)
        if complete:
            blocks['account'] = dict(blocks['account'] or {}, create_login=True)

        def write():
            if vals:
                parent.write(vals)
            if partner_vals:
                parent.name.write(partner_vals)
            apply_document_sets(parent, documents)
            if complete:
                _check_parent_complete(parent)
                parent.write({'active': True, 'bxi_is_draft': False})
            return _apply_security(parent, blocks)

        delivery, error = transaction(write)
        if error:
            return error
        return api_response(_with_credentials(_parent_detail(parent), parent, delivery))

    @http.route('/api/v1/parents/<int:parent_id>/discard', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def discard_parent_draft(self, parent_id, **kwargs):
        """Delete a parent draft saved with "Save Draft", with its files."""
        if not is_manager(request.env.user):
            return api_error('Not authorized to edit parents.', status=403, code='forbidden')
        parent = _parent_record(parent_id)
        if not parent:
            return api_error('Parent not found.', status=404, code='not_found')
        if not parent.bxi_is_draft:
            return api_error('Only a draft can be discarded.', status=400, code='not_a_draft')

        def discard():
            _discard(parent, 'op.parent', parent.name)
            return True

        _result, error = transaction(discard)
        if error:
            return error
        return api_response({'id': parent_id, 'discarded': True})
