# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import get_own_student_ids, parse_pagination, safe_create, user_can_access_student

STAFF_GROUP = 'bxi_certificate_management.group_certificate_user'
MANAGER_GROUP = 'bxi_certificate_management.group_certificate_manager'


def _is_certificate_staff(user):
    return user.has_group(STAFF_GROUP) or user.has_group(MANAGER_GROUP)


def _is_certificate_manager(user):
    return user.has_group(MANAGER_GROUP)


def _certificate_dict(cert):
    return {
        'id': cert.id,
        'certificate_number': cert.certificate_number,
        'certificate_type': cert.certificate_type_id.display_name,
        'student_id': cert.student_id.id,
        'course': cert.course_id.display_name,
        'issue_date': cert.issue_date and cert.issue_date.isoformat(),
        'expiry_date': cert.expiry_date and cert.expiry_date.isoformat(),
        'verification_code': cert.verification_code,
        'state': cert.state,
        'approved_by': cert.approved_by.name or None,
        'revoke_reason': cert.revoke_reason,
    }


class BxiApiSupportCertificateController(http.Controller):

    @http.route('/api/v1/certificates', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_certificates(self, **kwargs):
        user = request.env.user
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        if _is_certificate_staff(user):
            domain = []
        else:
            domain = [('student_id', 'in', get_own_student_ids(request.env)), ('state', '=', 'issued')]
        Certificate = request.env['op.certificate'].sudo()
        total = Certificate.search_count(domain)
        certs = Certificate.search(domain, limit=limit, offset=offset, order='issue_date desc')
        return api_response(
            {'certificates': [_certificate_dict(c) for c in certs]},
            meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/certificates/verify', type='http', auth='public', methods=['GET'], csrf=False)
    def verify_certificate(self, code=None, **kwargs):
        if not code:
            return api_error('code is required.', status=400, code='missing_code')
        cert = request.env['op.certificate'].sudo().search([('verification_code', '=', code)], limit=1)
        if not cert:
            return api_response({'status': 'not_found'})
        if cert.state == 'revoked':
            status = 'revoked'
        elif cert.expiry_date and cert.expiry_date < fields.Date.today():
            status = 'expired'
        else:
            status = 'valid'
        return api_response({
            'status': status, 'certificate_number': cert.certificate_number,
            'certificate_type': cert.certificate_type_id.display_name,
            'student_name': cert.student_id.name, 'issue_date': cert.issue_date and cert.issue_date.isoformat(),
        })

    @http.route('/api/v1/certificates/<int:certificate_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_certificate(self, certificate_id, **kwargs):
        cert = request.env['op.certificate'].sudo().browse(certificate_id)
        if not cert.exists():
            return api_error('Certificate not found.', status=404, code='not_found')
        if not _is_certificate_staff(request.env.user) and not (
                cert.state == 'issued'
                and user_can_access_student(request.env, cert.student_id, is_staff=_is_certificate_staff)):
            return api_error('Not authorized for this certificate.', status=403, code='forbidden')
        return api_response(_certificate_dict(cert))

    @http.route('/api/v1/certificates', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_certificate(self, **kwargs):
        if not _is_certificate_staff(request.env.user):
            return api_error('Not authorized to create certificates.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        if not payload.get('student_id'):
            return api_error('student_id is required.', status=400, code='missing_student_id')
        if not payload.get('certificate_type_id'):
            return api_error('certificate_type_id is required.', status=400, code='missing_certificate_type_id')
        vals = {key: payload[key] for key in (
            'student_id', 'certificate_type_id', 'course_id', 'batch_id', 'subject_id', 'remarks', 'issue_date',
        ) if key in payload}
        cert, error = safe_create(request.env['op.certificate'].sudo(), vals)
        if error:
            return error
        return api_response(_certificate_dict(cert), status=201)

    @http.route('/api/v1/certificates/<int:certificate_id>/generate', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def generate_certificate(self, certificate_id, **kwargs):
        return self._transition(certificate_id, 'action_generate', staff_only=True)

    @http.route('/api/v1/certificates/<int:certificate_id>/issue', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def issue_certificate(self, certificate_id, **kwargs):
        return self._transition(certificate_id, 'action_issue', staff_only=True)

    @http.route('/api/v1/certificates/<int:certificate_id>/approve', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def approve_certificate(self, certificate_id, **kwargs):
        return self._transition(certificate_id, 'action_approve', manager_only=True)

    @http.route('/api/v1/certificates/<int:certificate_id>/reset', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reset_certificate(self, certificate_id, **kwargs):
        return self._transition(certificate_id, 'action_reset_to_draft', staff_only=True)

    @http.route('/api/v1/certificates/<int:certificate_id>/revoke', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def revoke_certificate(self, certificate_id, **kwargs):
        if not _is_certificate_manager(request.env.user):
            return api_error('Not authorized to revoke certificates.', status=403, code='forbidden')
        cert = request.env['op.certificate'].sudo().browse(certificate_id)
        if not cert.exists():
            return api_error('Certificate not found.', status=404, code='not_found')
        payload = request.get_json_data() or {}
        if not payload.get('reason'):
            return api_error('reason is required.', status=400, code='missing_reason')
        _, error = call_action(cert, 'action_revoke', reason=payload['reason'])
        if error:
            return error
        return api_response(_certificate_dict(cert))

    def _transition(self, certificate_id, method_name, staff_only=False, manager_only=False):
        user = request.env.user
        if manager_only and not _is_certificate_manager(user):
            return api_error('Not authorized for this action.', status=403, code='forbidden')
        if staff_only and not _is_certificate_staff(user):
            return api_error('Not authorized for this action.', status=403, code='forbidden')
        cert = request.env['op.certificate'].sudo().browse(certificate_id)
        if not cert.exists():
            return api_error('Certificate not found.', status=404, code='not_found')
        _, error = call_action(cert, method_name)
        if error:
            return error
        return api_response(_certificate_dict(cert))

    @http.route('/api/v1/certificates/bulk-create', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def bulk_create_certificates(self, **kwargs):
        if not _is_certificate_staff(request.env.user):
            return api_error('Not authorized to create certificates.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        if not payload.get('certificate_type_id'):
            return api_error('certificate_type_id is required.', status=400, code='missing_certificate_type_id')
        if not payload.get('student_ids'):
            return api_error('student_ids is required.', status=400, code='missing_student_ids')
        vals = {
            'certificate_type_id': payload['certificate_type_id'],
            'student_ids': [(6, 0, payload['student_ids'])],
        }
        if payload.get('course_id'):
            vals['course_id'] = payload['course_id']
        if payload.get('batch_id'):
            vals['batch_id'] = payload['batch_id']
        if payload.get('issue_date'):
            vals['issue_date'] = payload['issue_date']
        wizard, error = safe_create(request.env['op.certificate.bulk.wizard'].sudo(), vals)
        if error:
            return error
        _, error = call_action(wizard, 'action_create_certificates')
        if error:
            return error
        certs = request.env['op.certificate'].sudo().search(
            [('student_id', 'in', payload['student_ids']), ('certificate_type_id', '=', payload['certificate_type_id'])],
            order='id desc', limit=len(payload['student_ids']))
        return api_response({'certificates': [_certificate_dict(c) for c in certs]}, status=201)
