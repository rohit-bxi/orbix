# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The app's Admission Application (Help > Admission Support): a signed-in
student or parent fills an application in five steps - Personal,
Academic, Documents, Statement, Review - saving a draft as they go, then
submits it to the admission office. Built on OpenEduCat admissions
(bxi_student_learning adds the steps, documents and statement); the
public one-shot form stays at POST /admissions/apply."""
from odoo import fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_file_response, api_response, parse_int, require_auth

from odoo.addons.bxi_student_learning.models.admission import DOCUMENT_SLOTS, REQUIRED_RECOMMENDATIONS, STEPS

from .admission import APPLY_FIELDS, APPLY_ID_FIELDS, _admission_dict, _open_registers
from .common import json_body, parse_date
from .people_account import transaction
from .people_fields import _document_entries, apply_document_sets

STEP_KEYS = [key for key, _label in STEPS]
# OpenEduCat requires gender on every application, drafts included.
PERSONAL_REQUIRED = ('first_name', 'last_name', 'birth_date', 'email', 'gender')
MAX_STATEMENT = 5000
DOCUMENT_MAX_BYTES = 5 * 1024 * 1024


def _application_dict(admission):
    data = _admission_dict(admission, detail=True)
    missing = admission._bxi_missing_for_submit()
    blocked = {step for step, _key in missing}
    steps = [{'key': key, 'label': label, 'complete': key not in blocked} for key, label in STEPS
             if key != 'review']
    done = len([s for s in steps if s['complete']])
    data.update({
        'step': admission.bxi_step or 'personal',
        'steps': steps,
        'percent_complete': round(100.0 * done / (len(STEP_KEYS)), 0),
        'statement': admission.bxi_statement or None,
        'documents': {
            slot: {
                'label': label, 'required': required,
                'needed': REQUIRED_RECOMMENDATIONS if slot == 'recommendations' else (1 if required else 0),
                'max_files': max_files,
                'files': [{'id': a.id, 'name': a.name, 'mimetype': a.mimetype or None, 'size': a.file_size,
                           'uploaded_at': fields.Datetime.to_string(a.create_date)} for a in admission[field]],
            } for slot, (field, required, max_files, label) in DOCUMENT_SLOTS.items()
        },
        'missing': [{'step': step, 'field': key} for step, key in missing],
        'can_submit': admission.state == 'draft' and not missing,
    })
    return data


def _values(payload, creating=False):
    """(vals, documents, error) from a create / update body."""
    env = request.env
    vals = {}
    for key in APPLY_FIELDS:
        if key in payload:
            value = payload[key]
            if key == 'birth_date':
                value, error = parse_date(value, key)
                if error:
                    return None, None, error
            elif key == 'family_income':
                try:
                    value = float(value or 0)
                except (TypeError, ValueError):
                    return None, None, api_error('family_income must be a number.', status=400,
                                                 code='invalid_family_income')
            elif isinstance(value, str):
                value = value.strip()
            vals[key] = value or False
    for key in APPLY_ID_FIELDS:
        if key in payload:
            value, error = parse_int(payload[key], key) if payload[key] not in (None, '') else (False, None)
            if error:
                return None, None, error
            vals[key] = value
    if creating or any(key in vals for key in PERSONAL_REQUIRED):
        for key in PERSONAL_REQUIRED:
            if (creating or key in vals) and not vals.get(key):
                return None, None, api_error('%s is required.' % key, status=400, code='missing_%s' % key)
    if vals.get('gender') and vals['gender'] not in dict(env['op.admission']._fields['gender'].selection):
        return None, None, api_error('gender is not valid.', status=400, code='invalid_gender')
    if 'statement' in payload:
        statement = payload['statement']
        if statement is not None and not isinstance(statement, str):
            return None, None, api_error('statement must be text.', status=400, code='invalid_statement')
        if statement and len(statement) > MAX_STATEMENT:
            return None, None, api_error('The statement is limited to %s characters.' % MAX_STATEMENT, status=400,
                                         code='statement_too_long')
        vals['bxi_statement'] = (statement or '').strip() or False
    if 'step' in payload:
        if payload['step'] not in STEP_KEYS:
            return None, None, api_error('step must be one of %s.' % ', '.join(STEP_KEYS), status=400,
                                         code='invalid_step')
        vals['bxi_step'] = payload['step']
    documents = {}
    block = payload.get('documents')
    if block is not None:
        if not isinstance(block, dict) or set(block) - set(DOCUMENT_SLOTS):
            return None, None, api_error('documents may only contain %s.' % ', '.join(DOCUMENT_SLOTS),
                                         status=400, code='invalid_documents')
        for slot, entries in block.items():
            field, _required, max_files, label = DOCUMENT_SLOTS[slot]
            checked, error = _document_entries(entries, slot, 'documents.%s' % slot, DOCUMENT_MAX_BYTES)
            if error:
                return None, None, error
            if len(checked) > max_files:
                return None, None, api_error('%s: at most %s files.' % (label, max_files), status=400,
                                             code='too_many_files')
            documents[field] = checked
    return vals, documents, None


class BxiApiSupportAdmissionApplicationController(http.Controller):

    def _application(self, admission_id):
        admission = request.env['op.admission'].sudo().browse(admission_id).exists()
        if not admission or admission.bxi_applicant_user_id != request.env.user:
            return None, api_error('Application not found.', status=404, code='not_found')
        return admission, None

    @http.route('/api/v1/admissions/applications', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def my_applications(self, **kwargs):
        """The signed-in user's applications, drafts included, newest first."""
        applications = request.env['op.admission'].sudo().search(
            [('bxi_applicant_user_id', '=', request.env.user.id)], order='id desc')
        return api_response({'applications': [_application_dict(a) for a in applications]})

    @http.route('/api/v1/admissions/applications', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def start(self, **kwargs):
        """Start a draft with the Personal step: {"register_id" (an open
        intake, see /admissions/registers), "first_name", "last_name",
        "birth_date", "email", "gender" (m/f/o), and optionally middle_name, mobile,
        phone, street, street2, city, zip, state_id, country_id}."""
        env = request.env
        payload = json_body() or {}
        register_id, error = parse_int(payload.get('register_id'), 'register_id')
        if error:
            return error
        register = _open_registers().filtered(lambda r: r.id == register_id)
        if not register:
            return api_error('This intake is not accepting applications.', status=400, code='register_closed')
        vals, documents, error = _values(payload, creating=True)
        if error:
            return error
        vals.update({
            'name': ' '.join(filter(None, (vals['first_name'], vals.get('middle_name'), vals['last_name']))),
            'register_id': register.id, 'course_id': register.course_id.id,
            'application_date': fields.Datetime.now(), 'bxi_applicant_user_id': env.user.id,
            'bxi_step': vals.get('bxi_step') or 'academic',
        })

        def create():
            admission = env['op.admission'].sudo().create(vals)
            if documents:
                apply_document_sets(admission, documents)
            return admission

        admission, error = transaction(create)
        if error:
            return error
        return api_response(_application_dict(admission), status=201)

    @http.route('/api/v1/admissions/applications/<int:admission_id>', type='http', auth='public',
                methods=['GET'], csrf=False)
    @require_auth
    def get_application(self, admission_id, **kwargs):
        admission, error = self._application(admission_id)
        if error:
            return error
        return api_response(_application_dict(admission))

    @http.route('/api/v1/admissions/applications/<int:admission_id>/update', type='http', auth='public',
                methods=['POST'], csrf=False)
    @require_auth
    def update(self, admission_id, **kwargs):
        """Save Draft / Continue on any step: personal and academic fields
        (prev_institute_id, prev_course_id, prev_result, family_business,
        family_income), "documents": {transcripts | test_scores |
        recommendations | id_proof | additional: [attachment ids to keep
        and new base64 files]} (PDF, JPG or PNG, 5 MB each), "statement",
        and "step" (where the applicant is). Drafts only."""
        admission, error = self._application(admission_id)
        if error:
            return error
        if admission.state != 'draft':
            return api_error('A submitted application cannot be changed.', status=400, code='already_submitted')
        vals, documents, error = _values(json_body() or {})
        if error:
            return error
        if any(key in vals for key in ('first_name', 'middle_name', 'last_name')):
            vals['name'] = ' '.join(filter(None, (vals.get('first_name', admission.first_name),
                                                  vals.get('middle_name', admission.middle_name),
                                                  vals.get('last_name', admission.last_name))))

        def write():
            if vals:
                admission.write(vals)
            if documents:
                apply_document_sets(admission, documents)
            return True

        _result, error = transaction(write)
        if error:
            return error
        return api_response(_application_dict(admission))

    @http.route('/api/v1/admissions/applications/<int:admission_id>/submit', type='http', auth='public',
                methods=['POST'], csrf=False)
    @require_auth
    def submit(self, admission_id, **kwargs):
        """Review > Submit: every step complete (both recommendation
        letters included), then it goes to the admission office."""
        admission, error = self._application(admission_id)
        if error:
            return error
        if admission.state != 'draft':
            return api_error('This application was already submitted.', status=400, code='already_submitted')
        missing = admission._bxi_missing_for_submit()
        if missing:
            return request.make_json_response({'success': False, 'error': {
                'message': 'Complete every step before submitting.', 'code': 'incomplete',
                'missing': [{'step': step, 'field': key} for step, key in missing]}}, status=400)
        admission.write({'bxi_step': 'review'})
        admission.submit_form()
        return api_response(_application_dict(admission))

    @http.route('/api/v1/admissions/applications/<int:admission_id>/discard', type='http', auth='public',
                methods=['POST'], csrf=False)
    @require_auth
    def discard(self, admission_id, **kwargs):
        admission, error = self._application(admission_id)
        if error:
            return error
        if admission.state != 'draft':
            return api_error('Only a draft can be discarded.', status=400, code='already_submitted')
        attachments = request.env['ir.attachment'].sudo()
        for field, *_rest in DOCUMENT_SLOTS.values():
            attachments |= admission[field]
        admission.unlink()
        attachments.exists().unlink()
        return api_response({'id': admission_id, 'discarded': True})

    @http.route('/api/v1/admissions/applications/<int:admission_id>/documents/<int:attachment_id>', type='http',
                auth='public', methods=['GET'], csrf=False)
    @require_auth
    def document(self, admission_id, attachment_id, **kwargs):
        admission, error = self._application(admission_id)
        if error:
            return error
        files = request.env['ir.attachment'].sudo()
        for field, *_rest in DOCUMENT_SLOTS.values():
            files |= admission[field]
        attachment = files.filtered(lambda a: a.id == attachment_id)
        if not attachment:
            return api_error('Document not found.', status=404, code='not_found')
        return api_file_response(attachment.raw, attachment.name, attachment.mimetype or 'application/octet-stream')
