# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

"""Health-center endpoints. Unlike fees/canteen/uniform/transport, this
module's own security model grants NO parent/student self-access to health
records at all (no ir.rule, no portal ACL) - only health staff/managers and,
on visits only, faculty can see anything. To avoid inventing an access path
that doesn't exist in the underlying module, every endpoint here (read and
write) is gated to health staff/managers only.
"""
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import parse_pagination, safe_create

STAFF_GROUP = 'op_health_center.group_health_staff'
MANAGER_GROUP = 'op_health_center.group_health_manager'


def _is_health_staff(user):
    return user.has_group(STAFF_GROUP) or user.has_group(MANAGER_GROUP)


def _visit_dict(visit):
    return {
        'id': visit.id, 'name': visit.name, 'type': visit.type,
        'patient_type': visit.patient_type, 'patient_name': visit.patient_name,
        'visit_datetime': visit.visit_datetime and visit.visit_datetime.isoformat(),
        'visit_type': visit.visit_type, 'symptoms': visit.symptoms, 'diagnosis': visit.diagnosis,
        'treatment_given': visit.treatment_given, 'referred_to_hospital': visit.referred_to_hospital,
        'state': visit.state,
    }


def _checkup_dict(checkup):
    return {
        'id': checkup.id, 'name': checkup.name, 'type': checkup.type,
        'patient_type': checkup.patient_type, 'patient_name': checkup.patient_name,
        'checkup_date': checkup.checkup_date and checkup.checkup_date.isoformat(),
        'checkup_type': checkup.checkup_type, 'height_cm': checkup.height_cm, 'weight_kg': checkup.weight_kg,
        'bmi': checkup.bmi, 'bmi_category': checkup.bmi_category, 'fitness_status': checkup.fitness_status,
        'state': checkup.state,
    }


def _vaccination_dict(vaccination):
    return {
        'id': vaccination.id, 'name': vaccination.name, 'type': vaccination.type,
        'patient_type': vaccination.patient_type, 'patient_name': vaccination.patient_name,
        'vaccine': vaccination.vaccine_id.display_name, 'dose_number': vaccination.dose_number,
        'scheduled_date': vaccination.scheduled_date and vaccination.scheduled_date.isoformat(),
        'date_administered': vaccination.date_administered and vaccination.date_administered.isoformat(),
        'next_due_date': vaccination.next_due_date and vaccination.next_due_date.isoformat(),
        'state': vaccination.state,
    }


class BxiApiSupportHealthController(http.Controller):

    # -- Visits --------------------------------------------------------------

    @http.route('/api/v1/health/visits', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_visits(self, **kwargs):
        if not _is_health_staff(request.env.user):
            return api_error('Not authorized to view health records.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Visit = request.env['op.health.visit'].sudo()
        total = Visit.search_count([])
        visits = Visit.search([], limit=limit, offset=offset, order='visit_datetime desc')
        return api_response(
            {'visits': [_visit_dict(v) for v in visits]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/health/visits/<int:visit_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_visit(self, visit_id, **kwargs):
        if not _is_health_staff(request.env.user):
            return api_error('Not authorized to view health records.', status=403, code='forbidden')
        visit = request.env['op.health.visit'].sudo().browse(visit_id)
        if not visit.exists():
            return api_error('Visit not found.', status=404, code='not_found')
        return api_response(_visit_dict(visit))

    @http.route('/api/v1/health/visits', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_visit(self, **kwargs):
        if not _is_health_staff(request.env.user):
            return api_error('Not authorized to record health visits.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        student_id, faculty_id = payload.get('student_id'), payload.get('faculty_id')
        if not student_id and not faculty_id:
            return api_error('student_id or faculty_id is required.', status=400, code='missing_patient')
        vals = {key: payload[key] for key in (
            'student_id', 'faculty_id', 'visit_type', 'symptoms', 'diagnosis', 'treatment_given',
            'referred_to_hospital', 'hospital_name', 'follow_up_required', 'follow_up_date',
        ) if key in payload}
        visit, error = safe_create(request.env['op.health.visit'].sudo(), vals)
        if error:
            return error
        return api_response(_visit_dict(visit), status=201)

    @http.route('/api/v1/health/visits/<int:visit_id>/confirm', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def confirm_visit(self, visit_id, **kwargs):
        return self._visit_transition(visit_id, 'action_confirm')

    @http.route('/api/v1/health/visits/<int:visit_id>/start-treatment', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def start_treatment_visit(self, visit_id, **kwargs):
        return self._visit_transition(visit_id, 'action_start_treatment')

    @http.route('/api/v1/health/visits/<int:visit_id>/resolve', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def resolve_visit(self, visit_id, **kwargs):
        return self._visit_transition(visit_id, 'action_resolve')

    @http.route('/api/v1/health/visits/<int:visit_id>/refer', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def refer_visit(self, visit_id, **kwargs):
        return self._visit_transition(visit_id, 'action_refer')

    @http.route('/api/v1/health/visits/<int:visit_id>/cancel', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def cancel_visit(self, visit_id, **kwargs):
        return self._visit_transition(visit_id, 'action_cancel')

    @http.route('/api/v1/health/visits/<int:visit_id>/reset', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reset_visit(self, visit_id, **kwargs):
        return self._visit_transition(visit_id, 'action_reset_draft')

    def _visit_transition(self, visit_id, method_name):
        if not _is_health_staff(request.env.user):
            return api_error('Not authorized to manage health visits.', status=403, code='forbidden')
        visit = request.env['op.health.visit'].sudo().browse(visit_id)
        if not visit.exists():
            return api_error('Visit not found.', status=404, code='not_found')
        _, error = call_action(visit, method_name)
        if error:
            return error
        return api_response(_visit_dict(visit))

    # -- Checkups --------------------------------------------------------------

    @http.route('/api/v1/health/checkups', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_checkups(self, **kwargs):
        if not _is_health_staff(request.env.user):
            return api_error('Not authorized to view health records.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Checkup = request.env['op.health.checkup'].sudo()
        total = Checkup.search_count([])
        checkups = Checkup.search([], limit=limit, offset=offset, order='checkup_date desc')
        return api_response(
            {'checkups': [_checkup_dict(c) for c in checkups]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/health/checkups/<int:checkup_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_checkup(self, checkup_id, **kwargs):
        if not _is_health_staff(request.env.user):
            return api_error('Not authorized to view health records.', status=403, code='forbidden')
        checkup = request.env['op.health.checkup'].sudo().browse(checkup_id)
        if not checkup.exists():
            return api_error('Checkup not found.', status=404, code='not_found')
        return api_response(_checkup_dict(checkup))

    @http.route('/api/v1/health/checkups', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_checkup(self, **kwargs):
        if not _is_health_staff(request.env.user):
            return api_error('Not authorized to record health checkups.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        student_id, faculty_id = payload.get('student_id'), payload.get('faculty_id')
        if not student_id and not faculty_id:
            return api_error('student_id or faculty_id is required.', status=400, code='missing_patient')
        vals = {key: payload[key] for key in (
            'student_id', 'faculty_id', 'checkup_date', 'checkup_type', 'height_cm', 'weight_kg',
            'blood_pressure', 'vision_left', 'vision_right', 'dental_status', 'general_remarks', 'fitness_status',
        ) if key in payload}
        checkup, error = safe_create(request.env['op.health.checkup'].sudo(), vals)
        if error:
            return error
        return api_response(_checkup_dict(checkup), status=201)

    @http.route('/api/v1/health/checkups/<int:checkup_id>/complete', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def complete_checkup(self, checkup_id, **kwargs):
        return self._checkup_transition(checkup_id, 'action_complete')

    @http.route('/api/v1/health/checkups/<int:checkup_id>/cancel', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def cancel_checkup(self, checkup_id, **kwargs):
        return self._checkup_transition(checkup_id, 'action_cancel')

    @http.route('/api/v1/health/checkups/<int:checkup_id>/reset', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reset_checkup(self, checkup_id, **kwargs):
        return self._checkup_transition(checkup_id, 'action_reset')

    def _checkup_transition(self, checkup_id, method_name):
        if not _is_health_staff(request.env.user):
            return api_error('Not authorized to manage health checkups.', status=403, code='forbidden')
        checkup = request.env['op.health.checkup'].sudo().browse(checkup_id)
        if not checkup.exists():
            return api_error('Checkup not found.', status=404, code='not_found')
        _, error = call_action(checkup, method_name)
        if error:
            return error
        return api_response(_checkup_dict(checkup))

    # -- Vaccinations ----------------------------------------------------------

    @http.route('/api/v1/health/vaccinations', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_vaccinations(self, **kwargs):
        if not _is_health_staff(request.env.user):
            return api_error('Not authorized to view health records.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Vaccination = request.env['op.health.vaccination'].sudo()
        total = Vaccination.search_count([])
        vaccinations = Vaccination.search([], limit=limit, offset=offset, order='scheduled_date desc')
        return api_response(
            {'vaccinations': [_vaccination_dict(v) for v in vaccinations]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/health/vaccinations/<int:vaccination_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_vaccination(self, vaccination_id, **kwargs):
        if not _is_health_staff(request.env.user):
            return api_error('Not authorized to view health records.', status=403, code='forbidden')
        vaccination = request.env['op.health.vaccination'].sudo().browse(vaccination_id)
        if not vaccination.exists():
            return api_error('Vaccination not found.', status=404, code='not_found')
        return api_response(_vaccination_dict(vaccination))

    @http.route('/api/v1/health/vaccinations', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_vaccination(self, **kwargs):
        if not _is_health_staff(request.env.user):
            return api_error('Not authorized to record vaccinations.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        student_id, faculty_id = payload.get('student_id'), payload.get('faculty_id')
        if not student_id and not faculty_id:
            return api_error('student_id or faculty_id is required.', status=400, code='missing_patient')
        if not payload.get('vaccine_id'):
            return api_error('vaccine_id is required.', status=400, code='missing_vaccine_id')
        vals = {key: payload[key] for key in (
            'student_id', 'faculty_id', 'vaccine_id', 'dose_number', 'scheduled_date',
            'date_administered', 'next_due_date', 'batch_no',
        ) if key in payload}
        vaccination, error = safe_create(request.env['op.health.vaccination'].sudo(), vals)
        if error:
            return error
        return api_response(_vaccination_dict(vaccination), status=201)

    @http.route('/api/v1/health/vaccinations/<int:vaccination_id>/complete', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def complete_vaccination(self, vaccination_id, **kwargs):
        return self._vaccination_transition(vaccination_id, 'action_complete')

    @http.route('/api/v1/health/vaccinations/<int:vaccination_id>/miss', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def miss_vaccination(self, vaccination_id, **kwargs):
        return self._vaccination_transition(vaccination_id, 'action_miss')

    @http.route('/api/v1/health/vaccinations/<int:vaccination_id>/cancel', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def cancel_vaccination(self, vaccination_id, **kwargs):
        return self._vaccination_transition(vaccination_id, 'action_cancel')

    @http.route('/api/v1/health/vaccinations/<int:vaccination_id>/reset', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reset_vaccination(self, vaccination_id, **kwargs):
        return self._vaccination_transition(vaccination_id, 'action_reset')

    def _vaccination_transition(self, vaccination_id, method_name):
        if not _is_health_staff(request.env.user):
            return api_error('Not authorized to manage vaccinations.', status=403, code='forbidden')
        vaccination = request.env['op.health.vaccination'].sudo().browse(vaccination_id)
        if not vaccination.exists():
            return api_error('Vaccination not found.', status=404, code='not_found')
        _, error = call_action(vaccination, method_name)
        if error:
            return error
        return api_response(_vaccination_dict(vaccination))
