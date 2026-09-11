# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import parse_pagination, safe_create

COORDINATOR_GROUP = 'bxi_rte_admission.group_rte_school_coordinator'
DISTRICT_OFFICER_GROUP = 'bxi_rte_admission.group_rte_district_officer'
ADMIN_GROUP = 'bxi_rte_admission.group_rte_admin'


def _is_rte_staff(user):
    return user.has_group(COORDINATOR_GROUP) or user.has_group(DISTRICT_OFFICER_GROUP) or user.has_group(ADMIN_GROUP)


def _is_rte_district_or_admin(user):
    return user.has_group(DISTRICT_OFFICER_GROUP) or user.has_group(ADMIN_GROUP)


def _admission_dict(admission):
    return {
        'id': admission.id,
        'application_number': admission.application_number,
        'name': admission.name,
        'course': admission.course_id.display_name,
        'rte_state': admission.rte_state,
        'rte_aadhaar_number': admission.rte_aadhaar_number,
        'confirmation_deadline': admission.confirmation_deadline and admission.confirmation_deadline.isoformat(),
        'doc_verification_deadline': admission.doc_verification_deadline and admission.doc_verification_deadline.isoformat(),
        'verified_by': admission.verified_by.name or None,
        'rejection_reason': admission.rejection_reason,
        'preferences': [{'course': p.course_id.display_name, 'sequence': p.sequence}
                        for p in admission.rte_preference_ids],
    }


def _grievance_dict(grievance):
    return {
        'id': grievance.id,
        'name': grievance.name,
        'admission_id': grievance.admission_id.id,
        'description': grievance.description,
        'state': grievance.state,
        'cbeo_resolution_notes': grievance.cbeo_resolution_notes,
        'jd_resolution_notes': grievance.jd_resolution_notes,
    }


def _batch_dict(batch):
    return {
        'id': batch.id,
        'name': batch.name,
        'course': batch.course_id.display_name,
        'academic_year': batch.academic_year_id.display_name,
        'state': batch.state,
        'effective_seats': batch.effective_seats,
        'draw_date': batch.draw_date and batch.draw_date.isoformat(),
        'results': [{
            'admission_id': r.admission_id.id, 'rank': r.rank, 'result_type': r.result_type,
            'preference_matched': r.preference_matched,
        } for r in batch.result_ids],
    }


def _claim_dict(claim):
    return {
        'id': claim.id,
        'name': claim.name,
        'course': claim.course_id.display_name,
        'academic_year': claim.academic_year_id.display_name,
        'admission_id': claim.admission_id.id or None,
        'installment': claim.installment,
        'actual_fee_charged': claim.actual_fee_charged,
        'amount': claim.amount,
        'state': claim.state,
    }


class BxiApiSupportRteAdmissionController(http.Controller):

    # -- Admissions ------------------------------------------------------------

    @http.route('/api/v1/admissions/rte', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_admissions(self, **kwargs):
        user = request.env.user
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        base_domain = [('is_rte_applicant', '=', True)]
        if _is_rte_staff(user):
            domain = base_domain
        else:
            domain = base_domain + [('partner_id', '=', user.partner_id.id)]
        Admission = request.env['op.admission'].sudo()
        total = Admission.search_count(domain)
        admissions = Admission.search(domain, limit=limit, offset=offset, order='id desc')
        return api_response(
            {'admissions': [_admission_dict(a) for a in admissions]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/admissions/rte/<int:admission_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_admission(self, admission_id, **kwargs):
        admission, error = self._authorized_admission(admission_id)
        if error:
            return error
        return api_response(_admission_dict(admission))

    @http.route('/api/v1/admissions/rte/<int:admission_id>/verify-documents', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def verify_documents(self, admission_id, **kwargs):
        return self._staff_transition(admission_id, 'action_verify_documents')

    @http.route('/api/v1/admissions/rte/<int:admission_id>/reject-documents', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reject_documents(self, admission_id, **kwargs):
        if not _is_rte_staff(request.env.user):
            return api_error('Not authorized for this action.', status=403, code='forbidden')
        admission = request.env['op.admission'].sudo().browse(admission_id)
        if not admission.exists():
            return api_error('Admission not found.', status=404, code='not_found')
        payload = request.get_json_data() or {}
        if payload.get('rejection_reason'):
            admission.rejection_reason = payload['rejection_reason']
        _, error = call_action(admission, 'action_reject_documents')
        if error:
            return error
        return api_response(_admission_dict(admission))

    @http.route('/api/v1/admissions/rte/<int:admission_id>/confirm', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def confirm_admission(self, admission_id, **kwargs):
        admission, error = self._authorized_admission(admission_id)
        if error:
            return error
        _, error = call_action(admission, 'action_confirm_admission')
        if error:
            return error
        return api_response(_admission_dict(admission))

    @http.route('/api/v1/admissions/rte/<int:admission_id>/mark-admitted', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def mark_admitted(self, admission_id, **kwargs):
        return self._staff_transition(admission_id, 'action_mark_admitted')

    @http.route('/api/v1/admissions/rte/<int:admission_id>/mark-lapsed', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def mark_lapsed(self, admission_id, **kwargs):
        return self._staff_transition(admission_id, 'action_mark_lapsed')

    def _staff_transition(self, admission_id, method_name):
        if not _is_rte_staff(request.env.user):
            return api_error('Not authorized for this action.', status=403, code='forbidden')
        admission = request.env['op.admission'].sudo().browse(admission_id)
        if not admission.exists():
            return api_error('Admission not found.', status=404, code='not_found')
        _, error = call_action(admission, method_name)
        if error:
            return error
        return api_response(_admission_dict(admission))

    def _authorized_admission(self, admission_id):
        admission = request.env['op.admission'].sudo().browse(admission_id)
        if not admission.exists() or not admission.is_rte_applicant:
            return None, api_error('Admission not found.', status=404, code='not_found')
        user = request.env.user
        if _is_rte_staff(user) or admission.partner_id.id == user.partner_id.id:
            return admission, None
        return None, api_error('Not authorized for this admission.', status=403, code='forbidden')

    # -- Grievances --------------------------------------------------------------

    @http.route('/api/v1/admissions/rte/<int:admission_id>/grievances', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_grievances(self, admission_id, **kwargs):
        admission, error = self._authorized_admission(admission_id)
        if error:
            return error
        return api_response({'grievances': [_grievance_dict(g) for g in admission.rte_grievance_ids]})

    @http.route('/api/v1/admissions/rte/<int:admission_id>/grievances', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def file_grievance(self, admission_id, **kwargs):
        admission, error = self._authorized_admission(admission_id)
        if error:
            return error
        payload = request.get_json_data() or {}
        if not payload.get('description'):
            return api_error('description is required.', status=400, code='missing_description')
        grievance, error = call_action(admission, 'action_file_grievance', description=payload['description'])
        if error:
            return error
        return api_response(_grievance_dict(grievance), status=201)

    @http.route('/api/v1/admissions/rte/grievances/<int:grievance_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_grievance(self, grievance_id, **kwargs):
        grievance = request.env['rte.grievance'].sudo().browse(grievance_id)
        if not grievance.exists():
            return api_error('Grievance not found.', status=404, code='not_found')
        user = request.env.user
        if not _is_rte_staff(user) and grievance.admission_id.partner_id.id != user.partner_id.id:
            return api_error('Not authorized for this grievance.', status=403, code='forbidden')
        return api_response(_grievance_dict(grievance))

    @http.route('/api/v1/admissions/rte/grievances/<int:grievance_id>/cbeo-resolve', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def cbeo_resolve(self, grievance_id, **kwargs):
        return self._grievance_transition(grievance_id, 'action_cbeo_resolve', notes_field='cbeo_resolution_notes')

    @http.route('/api/v1/admissions/rte/grievances/<int:grievance_id>/escalate', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def escalate_grievance(self, grievance_id, **kwargs):
        return self._grievance_transition(grievance_id, 'action_escalate_to_jd')

    @http.route('/api/v1/admissions/rte/grievances/<int:grievance_id>/jd-resolve', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def jd_resolve(self, grievance_id, **kwargs):
        if not _is_rte_district_or_admin(request.env.user):
            return api_error('Not authorized for this action.', status=403, code='forbidden')
        return self._grievance_transition(grievance_id, 'action_jd_resolve', notes_field='jd_resolution_notes', skip_auth=True)

    @http.route('/api/v1/admissions/rte/grievances/<int:grievance_id>/reject', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reject_grievance(self, grievance_id, **kwargs):
        return self._grievance_transition(grievance_id, 'action_reject')

    def _grievance_transition(self, grievance_id, method_name, notes_field=None, skip_auth=False):
        if not skip_auth and not _is_rte_staff(request.env.user):
            return api_error('Not authorized for this action.', status=403, code='forbidden')
        grievance = request.env['rte.grievance'].sudo().browse(grievance_id)
        if not grievance.exists():
            return api_error('Grievance not found.', status=404, code='not_found')
        payload = request.get_json_data() or {}
        if notes_field and payload.get(notes_field):
            grievance.write({notes_field: payload[notes_field]})
        _, error = call_action(grievance, method_name)
        if error:
            return error
        return api_response(_grievance_dict(grievance))

    # -- Lottery batches -----------------------------------------------------------

    @http.route('/api/v1/admissions/rte/lottery-batches', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_lottery_batches(self, **kwargs):
        if not _is_rte_district_or_admin(request.env.user):
            return api_error('Not authorized to view lottery batches.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Batch = request.env['rte.lottery.batch'].sudo()
        total = Batch.search_count([])
        batches = Batch.search([], limit=limit, offset=offset, order='id desc')
        return api_response(
            {'batches': [_batch_dict(b) for b in batches]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/admissions/rte/lottery-batches/<int:batch_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_lottery_batch(self, batch_id, **kwargs):
        if not _is_rte_district_or_admin(request.env.user):
            return api_error('Not authorized to view lottery batches.', status=403, code='forbidden')
        batch = request.env['rte.lottery.batch'].sudo().browse(batch_id)
        if not batch.exists():
            return api_error('Lottery batch not found.', status=404, code='not_found')
        return api_response(_batch_dict(batch))

    @http.route('/api/v1/admissions/rte/lottery-batches', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_lottery_batch(self, **kwargs):
        if not _is_rte_district_or_admin(request.env.user):
            return api_error('Not authorized to create lottery batches.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        if not payload.get('course_id'):
            return api_error('course_id is required.', status=400, code='missing_course_id')
        if not payload.get('academic_year_id'):
            return api_error('academic_year_id is required.', status=400, code='missing_academic_year_id')
        batch, error = safe_create(request.env['rte.lottery.batch'].sudo(), {
            'course_id': payload['course_id'], 'academic_year_id': payload['academic_year_id'],
        })
        if error:
            return error
        return api_response(_batch_dict(batch), status=201)

    @http.route('/api/v1/admissions/rte/lottery-batches/<int:batch_id>/mark-ready', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def mark_ready_lottery_batch(self, batch_id, **kwargs):
        return self._lottery_transition(batch_id, 'action_mark_ready')

    @http.route('/api/v1/admissions/rte/lottery-batches/<int:batch_id>/run', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def run_lottery_batch(self, batch_id, **kwargs):
        return self._lottery_transition(batch_id, 'run_lottery')

    @http.route('/api/v1/admissions/rte/lottery-batches/<int:batch_id>/publish', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def publish_lottery_batch(self, batch_id, **kwargs):
        return self._lottery_transition(batch_id, 'action_publish')

    def _lottery_transition(self, batch_id, method_name):
        if not _is_rte_district_or_admin(request.env.user):
            return api_error('Not authorized for this action.', status=403, code='forbidden')
        batch = request.env['rte.lottery.batch'].sudo().browse(batch_id)
        if not batch.exists():
            return api_error('Lottery batch not found.', status=404, code='not_found')
        _, error = call_action(batch, method_name)
        if error:
            return error
        return api_response(_batch_dict(batch))

    @http.route('/api/v1/admissions/rte/lottery-batches/create-and-run', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_and_run_lottery(self, **kwargs):
        if not _is_rte_district_or_admin(request.env.user):
            return api_error('Not authorized to run a lottery.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        if not payload.get('course_id'):
            return api_error('course_id is required.', status=400, code='missing_course_id')
        if not payload.get('academic_year_id'):
            return api_error('academic_year_id is required.', status=400, code='missing_academic_year_id')
        wizard, error = safe_create(request.env['rte.lottery.wizard'].sudo(), {
            'course_id': payload['course_id'], 'academic_year_id': payload['academic_year_id'],
        })
        if error:
            return error
        _, error = call_action(wizard, 'action_create_and_run')
        if error:
            return error
        batch = request.env['rte.lottery.batch'].sudo().search(
            [('course_id', '=', payload['course_id']), ('academic_year_id', '=', payload['academic_year_id'])],
            order='id desc', limit=1)
        return api_response(_batch_dict(batch), status=201)

    # -- Reimbursement claims ------------------------------------------------------

    @http.route('/api/v1/admissions/rte/reimbursement-claims', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_claims(self, **kwargs):
        if not _is_rte_staff(request.env.user):
            return api_error('Not authorized to view reimbursement claims.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Claim = request.env['rte.reimbursement.claim'].sudo()
        total = Claim.search_count([])
        claims = Claim.search([], limit=limit, offset=offset, order='id desc')
        return api_response(
            {'claims': [_claim_dict(c) for c in claims]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/admissions/rte/reimbursement-claims/<int:claim_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_claim(self, claim_id, **kwargs):
        if not _is_rte_staff(request.env.user):
            return api_error('Not authorized to view reimbursement claims.', status=403, code='forbidden')
        claim = request.env['rte.reimbursement.claim'].sudo().browse(claim_id)
        if not claim.exists():
            return api_error('Reimbursement claim not found.', status=404, code='not_found')
        return api_response(_claim_dict(claim))

    @http.route('/api/v1/admissions/rte/reimbursement-claims', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_claim(self, **kwargs):
        if not _is_rte_staff(request.env.user):
            return api_error('Not authorized to create reimbursement claims.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        for field in ('course_id', 'academic_year_id', 'amount'):
            if payload.get(field) is None:
                return api_error('%s is required.' % field, status=400, code='missing_%s' % field)
        vals = {key: payload[key] for key in (
            'course_id', 'academic_year_id', 'admission_id', 'actual_fee_charged', 'installment', 'amount',
        ) if key in payload}
        claim, error = safe_create(request.env['rte.reimbursement.claim'].sudo(), vals)
        if error:
            return error
        return api_response(_claim_dict(claim), status=201)

    @http.route('/api/v1/admissions/rte/reimbursement-claims/<int:claim_id>/submit', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def submit_claim(self, claim_id, **kwargs):
        return self._claim_transition(claim_id, 'action_submit')

    @http.route('/api/v1/admissions/rte/reimbursement-claims/<int:claim_id>/approve', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def approve_claim(self, claim_id, **kwargs):
        return self._claim_transition(claim_id, 'action_approve')

    @http.route('/api/v1/admissions/rte/reimbursement-claims/<int:claim_id>/reject', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reject_claim(self, claim_id, **kwargs):
        return self._claim_transition(claim_id, 'action_reject')

    @http.route('/api/v1/admissions/rte/reimbursement-claims/<int:claim_id>/mark-paid', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def mark_paid_claim(self, claim_id, **kwargs):
        return self._claim_transition(claim_id, 'action_mark_paid')

    def _claim_transition(self, claim_id, method_name):
        if not _is_rte_staff(request.env.user):
            return api_error('Not authorized for this action.', status=403, code='forbidden')
        claim = request.env['rte.reimbursement.claim'].sudo().browse(claim_id)
        if not claim.exists():
            return api_error('Reimbursement claim not found.', status=404, code='not_found')
        _, error = call_action(claim, method_name)
        if error:
            return error
        return api_response(_claim_dict(claim))
