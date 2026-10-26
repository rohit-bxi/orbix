# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Admissions (openeducat_admission): open intakes, the public online
application and its status check, the admission office's workflow - and
the family side of RTE admission (apply, documents, lottery result) next
to rte_admission.py's staff routes."""
import base64

from odoo import fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import (
    api_error, api_response, call_action, parse_int, parse_request, rate_limit, require_auth,
)

from .common import date_str, parse_pagination, ref, safe_create

ADMISSION_STAFF_GROUPS = ('openeducat_admission.group_op_admission_user', 'openeducat_admission.group_op_admission_admin')
APPLY_FIELDS = (
    'first_name', 'middle_name', 'last_name', 'birth_date', 'gender', 'email', 'phone', 'mobile',
    'street', 'street2', 'city', 'zip', 'prev_institute_id', 'prev_course_id', 'prev_result',
    'family_business', 'family_income',
)
APPLY_ID_FIELDS = ('state_id', 'country_id', 'batch_id')
# action -> (method, states it may start from)
TRANSITIONS = {
    'confirm': ('confirm_in_progress', ('submit',)),
    'admit': ('admission_confirm', ('confirm', 'pending')),
    'enroll': ('enroll_student', ('admission',)),
    'pending': ('confirm_pending', ('submit', 'confirm')),
    'reject': ('confirm_rejected', ('submit', 'confirm', 'pending')),
    'cancel': ('confirm_cancel', ('draft', 'submit', 'confirm', 'pending', 'admission')),
    'reset-to-draft': ('confirm_to_draft', ('reject', 'cancel')),
}
RTE_EDITABLE_STATES = ('draft', 'doc_rejected')
MAX_RTE_CHOICES = 5


def _is_admission_staff(user):
    return any(user.has_group(group) for group in ADMISSION_STAFF_GROUPS)


def _register_dict(register):
    admitted = request.env['op.admission'].sudo().search_count(
        [('register_id', '=', register.id), ('state', '=', 'done')])
    return {
        'id': register.id,
        'name': register.name,
        'class': ref(register.course_id),
        'start_date': date_str(register.start_date),
        'end_date': date_str(register.end_date),
        'minimum_age': register.minimum_age_criteria,
        'seats': register.max_count or None,
        'seats_left': max(register.max_count - admitted, 0) if register.max_count else None,
        'application_fee': register.product_id.lst_price if register.product_id else 0.0,
    }


def _admission_dict(admission, detail=False):
    data = {
        'id': admission.id,
        'application_number': admission.application_number,
        'name': admission.name,
        'class': ref(admission.course_id),
        'section': ref(admission.batch_id),
        'register': ref(admission.register_id),
        'application_date': date_str(admission.application_date),
        'state': admission.state,
        'student_id': admission.student_id.id or None,
    }
    if detail:
        data.update({k: admission[k] or None for k in APPLY_FIELDS if k not in ('birth_date',)})
        data.update({'birth_date': date_str(admission.birth_date), 'state_id': ref(admission.state_id),
                     'country_id': ref(admission.country_id)})
    return data


def _open_registers():
    today = fields.Date.today()
    return request.env['op.admission.register'].sudo().search([
        ('state', '=', 'application'), ('start_date', '<=', today), ('end_date', '>=', today),
    ], order='start_date')


class BxiApiSupportAdmissionController(http.Controller):

    # -- public -----------------------------------------------------------------

    @http.route('/api/v1/admissions/registers', type='http', auth='public', methods=['GET'], csrf=False)
    def open_registers(self, **kwargs):
        """Intakes currently accepting applications. No login needed - this
        backs the app's "Apply for admission" screen."""
        return api_response({'registers': [_register_dict(r) for r in _open_registers()]})

    @http.route('/api/v1/admissions/apply', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('admission_apply', limit=5)
    def apply(self, **kwargs):
        """Public online application to an open intake. Returns the
        application number the family later uses with /admissions/status."""
        payload = request.get_json_data() or {}
        register_id, error = parse_int(payload.get('register_id'), 'register_id')
        if error:
            return error
        register = _open_registers().filtered(lambda r: r.id == register_id)
        if not register:
            return api_error('This intake is not accepting applications.', status=400, code='register_closed')
        for required in ('first_name', 'last_name', 'birth_date', 'email', 'mobile'):
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        vals = {k: payload[k] for k in APPLY_FIELDS if payload.get(k) not in (None, '')}
        for key in APPLY_ID_FIELDS:
            if payload.get(key):
                vals[key], error = parse_int(payload[key], key)
                if error:
                    return error
        vals.update({
            'name': ' '.join(filter(None, (payload['first_name'], payload.get('middle_name'), payload['last_name']))),
            'register_id': register.id,
            'course_id': register.course_id.id,
            'application_date': fields.Datetime.now(),
        })
        admission, error = safe_create(request.env['op.admission'].sudo(), vals)
        if error:
            return error
        admission.submit_form()
        return api_response({
            'id': admission.id, 'application_number': admission.application_number, 'state': admission.state,
        }, status=201)

    @http.route('/api/v1/admissions/status', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('admission_status', limit=10)
    def status(self, **kwargs):
        """{application_number, birth_date}: the applicant's current state.
        Both must match, so an application number alone reveals nothing."""
        payload = request.get_json_data() or {}
        if not payload.get('application_number') or not payload.get('birth_date'):
            return api_error('application_number and birth_date are required.', status=400, code='missing_fields')
        try:
            birth_date = fields.Date.to_date(payload['birth_date'])
        except ValueError:
            return api_error('birth_date must be YYYY-MM-DD.', status=400, code='invalid_date')
        admission = request.env['op.admission'].sudo().search([
            ('application_number', '=', payload['application_number']), ('birth_date', '=', birth_date),
        ], limit=1)
        if not admission:
            return api_error('No application matches these details.', status=404, code='not_found')
        return api_response({'application_number': admission.application_number, 'state': admission.state,
                             'class': ref(admission.course_id)})

    # -- admission office -------------------------------------------------------

    @http.route('/api/v1/admissions', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_admissions(self, state=None, register_id=None, q=None, **kwargs):
        if not _is_admission_staff(request.env.user):
            return api_error('Not authorized to view admissions.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = [('is_rte_applicant', '=', False)]
        if state:
            domain.append(('state', '=', state))
        if register_id:
            register_id, error = parse_int(register_id, 'register_id')
            if error:
                return error
            domain.append(('register_id', '=', register_id))
        if q:
            domain += ['|', ('name', 'ilike', q), ('application_number', 'ilike', q)]
        Admission = request.env['op.admission'].sudo()
        total = Admission.search_count(domain)
        admissions = Admission.search(domain, limit=limit, offset=offset, order='application_date desc')
        return api_response({'admissions': [_admission_dict(a) for a in admissions]},
                            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/admissions/<int:admission_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_admission(self, admission_id, **kwargs):
        if not _is_admission_staff(request.env.user):
            return api_error('Not authorized to view admissions.', status=403, code='forbidden')
        admission = request.env['op.admission'].sudo().browse(admission_id)
        if not admission.exists():
            return api_error('Admission not found.', status=404, code='not_found')
        return api_response(_admission_dict(admission, detail=True))

    @http.route('/api/v1/admissions/<int:admission_id>/<any("confirm", "admit", "enroll", "pending", "reject", "cancel", "reset-to-draft"):action>',
                type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def transition(self, admission_id, action, **kwargs):
        """Office workflow: confirm -> admit -> enroll (creates the student
        record), with pending/reject/cancel/reset-to-draft on the side."""
        if not _is_admission_staff(request.env.user):
            return api_error('Not authorized to process admissions.', status=403, code='forbidden')
        admission = request.env['op.admission'].sudo().browse(admission_id)
        if not admission.exists() or admission.is_rte_applicant:
            return api_error('Admission not found.', status=404, code='not_found')
        method, allowed_from = TRANSITIONS[action]
        if admission.state not in allowed_from:
            return api_error(f"Can't {action} an application that is {admission.state}.",
                             status=400, code='invalid_transition')
        _, error = call_action(admission, method)
        if error:
            return error
        return api_response(_admission_dict(admission, detail=True))

    # -- RTE, family side ---------------------------------------------------------

    @http.route('/api/v1/admissions/rte/apply', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def rte_apply(self, **kwargs):
        """The app version of /my/rte/apply: the same fields, with the ranked
        school choices as `course_ids` (1-5 RTE-active classes)."""
        payload = request.get_json_data() or {}
        Admission = request.env['op.admission']
        errors = Admission._rte_application_errors(payload)
        choice_ids = []
        for raw in payload.get('course_ids') or []:
            course_id, error = parse_int(raw, 'course_ids')
            if error:
                return error
            if course_id not in choice_ids:
                choice_ids.append(course_id)
        if not choice_ids:
            errors['course_ids'] = 'missing'
        elif len(choice_ids) > MAX_RTE_CHOICES:
            errors['course_ids'] = 'too_many'
        elif len(request.env['op.course'].sudo().search([('id', 'in', choice_ids), ('rte_active', '=', True)])) != len(choice_ids):
            errors['course_ids'] = 'not_rte_active'
        if errors:
            body = {'success': False, 'error': {'message': 'Please correct the highlighted fields.',
                                                 'code': 'validation_error', 'fields': errors}}
            return request.make_json_response(body, status=400)
        admission = Admission._rte_create_application(request.env.user.partner_id, payload, choice_ids)
        return api_response({'id': admission.id, 'application_number': admission.application_number,
                             'rte_state': admission.rte_state}, status=201)

    @http.route('/api/v1/admissions/rte/my', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def rte_my_applications(self, **kwargs):
        admissions = request.env['op.admission'].sudo().search([
            ('partner_id', '=', request.env.user.partner_id.id), ('is_rte_applicant', '=', True),
        ], order='application_date desc')
        return api_response({'applications': [{
            'id': a.id,
            'application_number': a.application_number,
            'name': a.name,
            'rte_state': a.rte_state,
            'preferences': [ref(p.course_id) for p in a.rte_preference_ids],
            'documents': [{'id': d.id, 'doc_type': d.doc_type, 'verification_status': d.verification_status,
                           'remarks': d.remarks or None} for d in a.rte_document_ids],
            'rejection_reason': a.rejection_reason or None,
        } for a in admissions]})

    def _own_rte_admission(self, admission_id):
        admission = request.env['op.admission'].sudo().browse(admission_id)
        if (not admission.exists() or not admission.is_rte_applicant
                or admission.partner_id != request.env.user.partner_id):
            return None, api_error('Application not found.', status=404, code='not_found')
        return admission, None

    @http.route('/api/v1/admissions/rte/<int:admission_id>/documents', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def rte_upload_document(self, admission_id, **kwargs):
        """Attach a supporting document (multipart `file` or base64
        `attachments`) with `doc_type`, while the application is still a
        draft or its documents were rejected. Re-uploading a type replaces
        the previous file."""
        admission, error = self._own_rte_admission(admission_id)
        if error:
            return error
        if admission.rte_state not in RTE_EDITABLE_STATES:
            return api_error('Documents can no longer be changed for this application.',
                             status=400, code='invalid_transition')
        payload, files, error = parse_request()
        if error:
            return error
        doc_types = dict(request.env['rte.document']._fields['doc_type'].selection)
        if payload.get('doc_type') not in doc_types:
            return api_error('doc_type must be one of %s.' % ', '.join(doc_types), status=400, code='invalid_doc_type')
        if not files:
            return api_error('A document file is required.', status=400, code='missing_file')
        Document = request.env['rte.document'].sudo()
        existing = Document.search([('admission_id', '=', admission.id), ('doc_type', '=', payload['doc_type'])])
        vals = {'document': base64.b64encode(files[0]['content']), 'document_filename': files[0]['name'],
                'verification_status': 'pending'}
        if existing:
            existing.write(vals)
            document = existing[0]
        else:
            document, error = safe_create(Document, dict(vals, admission_id=admission.id, doc_type=payload['doc_type']))
            if error:
                return error
        return api_response({'id': document.id, 'doc_type': document.doc_type,
                             'verification_status': document.verification_status}, status=201)

    @http.route('/api/v1/admissions/rte/<int:admission_id>/lottery-result', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def rte_lottery_result(self, admission_id, **kwargs):
        """The applicant's result, once its lottery batch is published."""
        admission, error = self._own_rte_admission(admission_id)
        if error:
            return error
        results = request.env['rte.lottery.result'].sudo().search([
            ('admission_id', '=', admission.id), ('batch_id.state', '=', 'published'),
        ])
        return api_response({'application_number': admission.application_number, 'rte_state': admission.rte_state,
                             'results': [{
                                 'batch': ref(r.batch_id),
                                 'rank': r.rank,
                                 'result_type': r.result_type,
                                 'preference_matched': r.preference_matched,
                             } for r in results]})
