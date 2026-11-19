# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Profile fields of the people directory (people.py): the body keys each
kind of person accepts, how each value is checked, and how it reads back.

Every key is optional on update and only the keys sent are changed. null
(or "") clears a value, except for the required ones, which answer 400
missing_<key>. Ids that do not exist answer 400 invalid_<key>.

Shared shapes:
  address objects  {"street", "street2", "city", "zip", "state_id", "country_id"},
                   ("address" may also be one line of text - the app's single
                   Address box - kept as the street)
  "health"         {"is_allergy", "allergy", "chronic_conditions", "disabilities",
                    "dietary_restrictions", "primary_physician", "physician_contact",
                    "insurance_provider", "insurance_policy_no", "medical_notes"}
  "documents"      (students, parents) {"<set>": [<file> | <attachment id>, ...]}
                   (parent sets: additional, aadhaar_card, pan_card, id_proof)
  "academic_documents" (teachers) [<file> | <attachment id>, ...] - the
                   Teacher Documents attachments of the Academic Details tab
                   A file is "<base64>" or {"data", "filename"} (image or PDF).
                   The list sent becomes the whole set: ids keep files already
                   there, files are added, anything left out is removed.
"""
import base64

from odoo import fields
from odoo.tools import html2plaintext, plaintext2html
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error

from ..models.people_service import PeopleError
from .common import check_selection, date_str, ref, resolve_record, resolve_records
from .people_account import _file_entry

CHAR, DATE, BOOL, NUMBER, SELECTION, LANG, M2O, M2M, HTML = (
    'char', 'date', 'bool', 'number', 'selection', 'lang', 'm2o', 'm2m', 'html')


class F:
    """One body key: the model field it writes, how its value is checked
    (`kind`), the comodel of a relation, and the response key it reads back
    as (`out`; False when another part of the response already shows it)."""

    __slots__ = ('field', 'kind', 'model', 'out')

    def __init__(self, field, kind=CHAR, model=None, out=None):
        self.field, self.kind, self.model, self.out = field, kind, model, out


def _spec(**entries):
    """{key: F}; the response key defaults to the body key without its
    _id/_ids suffix (title_id -> title, category_id -> category)."""
    spec = {}
    for key, entry in entries.items():
        if entry.out is None:
            entry.out = key[:-4] if key.endswith('_ids') else key[:-3] if key.endswith('_id') else key
        spec[key] = entry
    return spec


# Shown in the "address" object of every response, so not repeated at the
# top level.
_TOP_LEVEL_ADDRESS = dict(
    street=F('street', out=False), street2=F('street2', out=False), city=F('city', out=False),
    zip=F('zip', out=False), state_id=F('state_id', M2O, 'res.country.state', out=False),
    country_id=F('country_id', M2O, 'res.country', out=False),
)

_PERSON = dict(
    first_name=F('first_name'), middle_name=F('middle_name'), last_name=F('last_name'),
    title_id=F('title', M2O, 'res.partner.title'), gender=F('gender', SELECTION),
    birth_date=F('birth_date', DATE), email=F('email'), phone=F('phone'), blood_group=F('blood_group', SELECTION),
    nationality=F('nationality', M2O, 'res.country'), nationality_id=F('nationality', M2O, 'res.country', out=False),
    id_number=F('id_number'), lang=F('lang', LANG), religion=F('religion', SELECTION),
    category_id=F('category_id', M2O, 'op.category'), visa_info=F('visa_info'),
    is_allergy=F('is_allergy', BOOL, out=False), allergy=F('allergy', out=False),
    active=F('active', BOOL),
    **_TOP_LEVEL_ADDRESS,
)

STUDENT_SPEC = _spec(
    **_PERSON,
    # The Add New Student screen's "Admission Number" is the core
    # Registration Number (unique); "gr_no" stays accepted as before.
    admission_number=F('gr_no'), gr_no=F('gr_no', out=False),
    admission_date=F('admission_date', DATE), nick_name=F('nick_name'),
    # The screen's single "Medical Conditions / Allergies" box.
    medical_conditions=F('medical_notes'),
    # The form's Notes (rich text there; plain text here).
    notes=F('comment', HTML),
    # A student card from POST /library/cards (checked in people.py).
    library_card_id=F('library_card_id', M2O, 'op.library.card', out='library_card'),
    scolar_number=F('scolar_number'), enrollment_status=F('enrollment_status', SELECTION),
    mode_of_transport=F('mode_of_transport', SELECTION), trait=F('trait'), other_sibling=F('other_sibling'),
    pickup_person=F('pickup_person'), special_needs_and_abilities=F('special_needs_and_abilities'),
    parent_ids=F('parent_ids', M2M, 'op.parent', out=False),
)

TEACHER_SPEC = _spec(
    **_PERSON,
    teacher_code=F('teacher_code'),
    employee_id=F('emp_id', M2O, 'hr.employee', out='employee'),
    joining_date=F('joining_date', DATE), highest_qualification=F('highest_qualification'),
    years_of_experience=F('years_of_experience'), previous_school=F('previous_school'),
    certifications=F('certifications'), cast=F('cast'),
    main_department_id=F('main_department_id', M2O, 'op.department', out='department'),
    allowed_department_ids=F('allowed_department_ids', M2M, 'op.department', out='allowed_departments'),
)

PARENT_SPEC = _spec(
    # The parent's own email/mobile: also copied to their contact, which
    # login credentials are sent to (see _sync_parent_contact).
    mobile=F('mobile', out=False), email=F('email', out=False),
    # The Add / Edit Parent screen's "Phone Number" is the mobile.
    phone=F('mobile', out='phone'),
    gender=F('gender', SELECTION), birth_date=F('birth_date', DATE),
    relationship_id=F('relationship_id', M2O, 'op.parent.relationship'),
    **_TOP_LEVEL_ADDRESS,
)

REQUIRED = {
    # One-word names are allowed for students: last_name is optional.
    'op.student': ('first_name', 'gender', 'email'),
    'op.faculty': ('first_name', 'last_name', 'gender', 'birth_date'),
    'op.parent': ('mobile', 'phone', 'gender', 'relationship_id'),
}

# Also required when a student is created (or a draft completed) - the
# Add New Student screen's starred fields. Address, class/section and
# parent are checked by the controller.
STUDENT_CREATE_REQUIRED = ('birth_date', 'phone', 'admission_number', 'admission_date')
# The same for a parent (name, mobile, relationship and students are
# checked by the controller, address too).
PARENT_CREATE_REQUIRED = ('gender', 'birth_date', 'email')

# The screen's limits: 5 MB per student document.
DOCUMENT_MAX_BYTES = {'op.student': 5 * 1024 * 1024, 'op.parent': 5 * 1024 * 1024}

ADDRESS_SPEC = _spec(
    street=F('street'), street2=F('street2'), city=F('city'), zip=F('zip'),
    state_id=F('state_id', M2O, 'res.country.state'), country_id=F('country_id', M2O, 'res.country'),
)
# Teachers keep three more addresses next to the main one.
TEACHER_ADDRESSES = ('official', 'postal', 'regional')

HEALTH_SPEC = _spec(
    is_allergy=F('is_allergy', BOOL), allergy=F('allergy'), chronic_conditions=F('chronic_conditions'),
    disabilities=F('disabilities'), dietary_restrictions=F('dietary_restrictions'),
    primary_physician=F('primary_physician'), physician_contact=F('physician_contact'),
    insurance_provider=F('insurance_provider'), insurance_policy_no=F('insurance_policy_no'),
    medical_notes=F('medical_notes'),
)

RTE_SPEC = _spec(
    category=F('rte_category', SELECTION), annual_income=F('rte_annual_income', NUMBER),
    bpl_number=F('rte_bpl_number'), bpl_list_type=F('rte_bpl_list_type', SELECTION),
    income_certificate_financial_year=F('rte_income_certificate_financial_year'),
)
# RTE certificates: body key -> (binary field, filename field).
RTE_FILES = {
    'income_certificate': ('rte_income_certificate', 'rte_income_certificate_filename'),
    'category_certificate': ('rte_category_certificate', 'rte_category_certificate_filename'),
}

DOCUMENT_SETS = {
    'op.student': {
        'birth_certificate': 'birth_certificate_ids',
        'transfer_certificate': 'transfer_certificate_ids',
        'previous_school_certificate': 'previous_school_certificate_ids',
        'medical_records': 'medical_record_ids',
    },
    'op.parent': {
        'additional': 'additional_document_ids',
        # The Add / Edit Parent screen's Additional Documents.
        'aadhaar_card': 'bxi_aadhaar_card_ids',
        'pan_card': 'bxi_pan_card_ids',
        'id_proof': 'bxi_id_proof_ids',
    },
    # Sent as a plain "academic_documents" list (teachers' "documents" are
    # their typed teacher-document records).
    'op.faculty': {'academic_documents': 'teacher_documents_ids'},
}

WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday')


# -- parsing ----------------------------------------------------------------------------


def _blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _invalid(label, code_key, what):
    return api_error('%s must be %s.' % (label, what), status=400, code='invalid_%s' % code_key)


def _value(Model, key, entry, value, label):
    """(model value, error) for one non-blank body value."""
    kind = entry.kind
    if kind in (CHAR, HTML):
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            return None, _invalid(label, key, 'text')
        value = str(value).strip()
        return (plaintext2html(value) if kind == HTML else value), None
    if kind == DATE:
        try:
            return fields.Date.to_string(fields.Date.to_date(value)), None
        except (TypeError, ValueError):
            return None, _invalid(label, key, 'a date (YYYY-MM-DD)')
    if kind == BOOL:
        if not isinstance(value, (bool, int)):
            return None, _invalid(label, key, 'true or false')
        return bool(value), None
    if kind == NUMBER:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return None, _invalid(label, key, 'a number of 0 or more')
        return value, None
    if kind == SELECTION:
        error = check_selection(Model, entry.field, value, key=key)
        return (None, error) if error else (value, None)
    if kind == LANG:
        installed = dict(request.env['res.lang'].get_installed())
        if value not in installed:
            return None, _invalid(label, key, 'one of %s' % ', '.join(installed))
        return value, None
    if kind == M2O:
        record, error = resolve_record(request.env, entry.model, value, key)
        return (None, error) if error else (record.id, None)
    records, error = resolve_records(request.env, entry.model, value, key)
    return (None, error) if error else ([(6, 0, records.ids)], None)


def parse_fields(Model, payload, spec, required=(), prefix=''):
    """(vals, error) from the keys of `payload` that `spec` knows."""
    vals = {}
    for key, entry in spec.items():
        if key not in payload:
            continue
        value = payload[key]
        label = prefix + key
        if _blank(value) or (entry.kind == M2M and value == []):
            if key in required:
                return None, api_error('%s is required.' % label, status=400, code='missing_%s' % key)
            vals[entry.field] = [(6, 0, [])] if entry.kind == M2M else False
            continue
        vals[entry.field], error = _value(Model, key, entry, value, label)
        if error:
            return None, error
    return vals, None


def _block(payload, key):
    """(dict or None, error) for an optional object in the body; null or {}
    is an empty object."""
    if key not in payload:
        return None, None
    block = payload[key] or {}
    if not isinstance(block, dict):
        return None, api_error('%s must be an object.' % key, status=400, code='invalid_%s' % key)
    return block, None


def parse_address(Model, payload, key='address', prefix=''):
    """(vals, error) from an optional address object - the main "address"
    may also be a line of text, kept as the street; `prefix` names the
    teacher's extra addresses (official_street...)."""
    if key == 'address' and isinstance(payload.get(key), str):
        return {prefix + 'street': payload[key].strip() or False}, None
    block, error = _block(payload, key)
    if error or block is None:
        return {}, error
    vals, error = parse_fields(Model, block, ADDRESS_SPEC, prefix=key + '.')
    if error:
        return None, error
    return {prefix + field: value for field, value in vals.items()}, None


def parse_teacher_addresses(Model, payload):
    vals = {}
    for name in TEACHER_ADDRESSES:
        extra, error = parse_address(Model, payload, '%s_address' % name, prefix='%s_' % name)
        if error:
            return None, error
        vals.update(extra)
    return vals, None


def parse_health(Model, payload):
    block, error = _block(payload, 'health')
    if error or block is None:
        return {}, error
    return parse_fields(Model, block, HEALTH_SPEC, prefix='health.')


def parse_available_days(days):
    """{available_<day>: bool} from a list of weekday names."""
    if not isinstance(days, list) or any(day not in WEEKDAYS for day in days):
        return None, api_error('available_days must be a list of %s.' % ', '.join(WEEKDAYS), status=400,
                               code='invalid_available_days')
    return {'available_%s' % day: day in days for day in WEEKDAYS}, None


def parse_rte(Model, payload):
    """(vals, error) for a parent's "rte" object: RTE admission details and
    their certificates (a file, or null to remove it)."""
    block, error = _block(payload, 'rte')
    if error or block is None:
        return {}, error
    vals, error = parse_fields(Model, block, RTE_SPEC, prefix='rte.')
    if error:
        return None, error
    for key, (field, filename_field) in RTE_FILES.items():
        if key not in block:
            continue
        if _blank(block[key]):
            vals.update({field: False, filename_field: False})
            continue
        file, error = _file_entry(block[key], key)
        if error:
            return None, error
        vals.update({field: base64.b64encode(file['content']), filename_field: file['name']})
    return vals, None


def parse_document_sets(model, payload):
    """(sets, error): {field: [attachment id | file]} from an optional
    "documents" object of a student or parent."""
    block, error = _block(payload, 'documents')
    if error or block is None:
        return {}, error
    names = DOCUMENT_SETS[model]
    unknown = set(block) - set(names)
    if unknown:
        return None, api_error('documents may only contain %s.' % ', '.join(names), status=400,
                               code='invalid_documents')
    sets = {}
    for name, entries in block.items():
        sets[names[name]], error = _document_entries(entries, name, 'documents.%s' % name,
                                                     DOCUMENT_MAX_BYTES.get(model))
        if error:
            return None, error
    return sets, None


def _document_entries(entries, name, label, max_bytes=None):
    """(list of attachment ids and files, error) for one document set."""
    entries = entries or []
    if not isinstance(entries, list):
        return None, api_error('%s must be a list.' % label, status=400, code='invalid_documents')
    checked = []
    for index, entry in enumerate(entries):
        if isinstance(entry, int) and not isinstance(entry, bool):
            checked.append(entry)
            continue
        file, error = _file_entry(entry, name, index)
        if error:
            return None, error
        if max_bytes and len(file['content']) > max_bytes:
            return None, api_error('%s: each file must be %s MB or smaller.' % (label, max_bytes // (1024 * 1024)),
                                   status=413, code='file_too_large')
        checked.append(file)
    return checked, None


def parse_teacher_documents(payload):
    """(sets, error) for a teacher's optional "academic_documents" list."""
    if 'academic_documents' not in payload:
        return {}, None
    entries, error = _document_entries(payload['academic_documents'], 'academic_documents', 'academic_documents')
    if error:
        return None, error
    return {'teacher_documents_ids': entries}, None


# -- applying (inside the transaction) ----------------------------------------------------------


def apply_document_sets(record, sets):
    """Make each attachment set exactly the list sent: kept ids must already
    be in that set; files become new attachments of the record; attachments
    of the record that are left out are deleted."""
    Attachment = request.env['ir.attachment'].sudo()
    for field, entries in sets.items():
        current = record[field]
        keep = [entry for entry in entries if isinstance(entry, int)]
        unknown = set(keep) - set(current.ids)
        if unknown:
            raise PeopleError('documents: attachment %s is not one of this record\'s files.' % sorted(unknown)[0],
                              'invalid_documents')
        new = Attachment
        for file in (entry for entry in entries if isinstance(entry, dict)):
            new |= Attachment.create({
                'name': file['name'], 'raw': file['content'], 'mimetype': file['mimetype'],
                'res_model': record._name, 'res_id': record.id,
            })
        removed = current.filtered(lambda a: a.id not in keep)
        record.write({field: [(6, 0, keep + new.ids)]})
        removed.filtered(lambda a: a.res_model == record._name and a.res_id == record.id).unlink()


# -- response shapes ----------------------------------------------------------------------


def _read(record, entry):
    value = record[entry.field]
    if entry.kind == DATE:
        return date_str(value)
    if entry.kind == BOOL:
        return bool(value)
    if entry.kind == M2O:
        return ref(value)
    if entry.kind == M2M:
        return [ref(r) for r in value]
    if entry.kind == HTML:
        return html2plaintext(value).strip() or None if value else None
    return value if value or entry.kind == NUMBER else None


def fields_dict(record, spec):
    """The response values of every spec key that has a response key."""
    return {entry.out: _read(record, entry) for entry in spec.values() if entry.out}


def address_dict(record, prefix=''):
    return {
        'street': record[prefix + 'street'] or None, 'street2': record[prefix + 'street2'] or None,
        'city': record[prefix + 'city'] or None, 'zip': record[prefix + 'zip'] or None,
        'state': ref(record[prefix + 'state_id']), 'country': ref(record[prefix + 'country_id']),
    }


def health_dict(record):
    return fields_dict(record, HEALTH_SPEC)


def rte_dict(parent):
    data = fields_dict(parent, RTE_SPEC)
    for key, (field, filename_field) in RTE_FILES.items():
        data[key] = {'filename': parent[filename_field] or None} if parent[field] else None
    return data


def documents_dict(record):
    return {
        name: [{'id': a.id, 'name': a.name, 'mimetype': a.mimetype or None} for a in record[field]]
        for name, field in DOCUMENT_SETS[record._name].items()
    }


def emergency_contact_dict(record):
    contact = record.emergency_contact
    if not contact:
        return None
    data = {'name': contact.name, 'phone': contact.phone or None}
    if 'emergency_contact_relation' in record._fields:
        data['relation'] = record.emergency_contact_relation or None
    return data
