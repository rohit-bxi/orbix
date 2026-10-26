# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import http
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request

# Para 4.8: up to 5 ranked school preferences per application.
MAX_SCHOOL_CHOICES = 5


class RteAdmissionPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'rte_admission_count' in counters:
            values['rte_admission_count'] = request.env['op.admission'].sudo().search_count(
                [('partner_id', '=', request.env.user.partner_id.id),
                 ('is_rte_applicant', '=', True)])
        return values

    @http.route('/my/rte/applications', type='http', auth='user', website=True)
    def portal_my_rte_applications(self, **kw):
        admissions = request.env['op.admission'].sudo().search(
            [('partner_id', '=', request.env.user.partner_id.id),
             ('is_rte_applicant', '=', True)],
            order='application_date desc')
        return request.render('bxi_rte_admission.portal_my_rte_applications', {
            'admissions': admissions,
            'page_name': 'rte_admission',
        })

    @http.route('/my/rte/grievance/<int:admission_id>', type='http', auth='user',
                website=True, methods=['POST'])
    def portal_rte_file_grievance(self, admission_id, **kw):
        """Para 6.6/8.3: a parent dissatisfied with a Rejected document
        verification decision can file an online grievance against it."""
        admission = request.env['op.admission'].sudo().search([
            ('id', '=', admission_id),
            ('partner_id', '=', request.env.user.partner_id.id),
            ('is_rte_applicant', '=', True),
        ], limit=1)
        if admission and kw.get('description'):
            admission.action_file_grievance(kw['description'])
        return request.redirect('/my/rte/applications')

    @http.route('/my/rte/apply', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_rte_apply(self, **kw):
        courses = request.env['op.course'].sudo().search([('rte_active', '=', True)])
        error = {}
        if http.request.httprequest.method == 'POST':
            Admission = request.env['op.admission']
            error = Admission._rte_application_errors(kw)
            if not kw.get('course_id_1'):
                error['course_id_1'] = 'missing'

            choice_ids = []
            if not error:
                seen = set()
                for i in range(1, MAX_SCHOOL_CHOICES + 1):
                    raw = kw.get('course_id_%s' % i)
                    if not raw:
                        continue
                    course_id = int(raw)
                    if course_id in seen:
                        error['course_id_%s' % i] = 'duplicate'
                        continue
                    seen.add(course_id)
                    choice_ids.append(course_id)

            if not error:
                admission = Admission._rte_create_application(request.env.user.partner_id, kw, choice_ids)
                return request.redirect('/my/rte/applications?created=%s' % admission.id)

        return request.render('bxi_rte_admission.portal_rte_apply_form', {
            'courses': courses,
            'error': error,
            'kw': kw,
            'max_choices': range(1, MAX_SCHOOL_CHOICES + 1),
        })
