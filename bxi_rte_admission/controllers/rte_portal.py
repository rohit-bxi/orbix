# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, http
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request

# Para 4.8: up to 5 ranked school preferences per application.
MAX_SCHOOL_CHOICES = 5
# Para 4.4: an already-admitted child cannot apply again.
RTE_ACTIVE_SEAT_STATES = ('allotted', 'confirmed', 'admitted')


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
            required = ['first_name', 'last_name', 'birth_date', 'email',
                        'mobile', 'course_id_1']
            for field_name in required:
                if not kw.get(field_name):
                    error[field_name] = 'missing'

            if not (kw.get('rte_aadhaar_number') or kw.get('rte_aadhaar_enrollment_number')):
                error['rte_aadhaar_number'] = 'missing'

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
                aadhaar_domain = []
                if kw.get('rte_aadhaar_number'):
                    aadhaar_domain.append(
                        ('rte_aadhaar_number', '=', kw['rte_aadhaar_number']))
                if kw.get('rte_aadhaar_enrollment_number'):
                    aadhaar_domain.append(
                        ('rte_aadhaar_enrollment_number', '=',
                         kw['rte_aadhaar_enrollment_number']))
                or_domain = ['|'] * (len(aadhaar_domain) - 1) + aadhaar_domain
                already_admitted = request.env['op.admission'].sudo().search([
                    ('is_rte_applicant', '=', True),
                    ('rte_state', 'in', RTE_ACTIVE_SEAT_STATES),
                ] + or_domain, limit=1) if aadhaar_domain else False
                if already_admitted:
                    error['rte_aadhaar_number'] = 'already_admitted'

            if not error:
                partner = request.env.user.partner_id
                register = request.env['op.admission.register'].sudo().search(
                    [('course_id', '=', choice_ids[0])], limit=1)
                if not register:
                    register = request.env['op.admission.register'].sudo().search(
                        [], limit=1)

                parent = request.env['op.parent'].sudo().search(
                    [('name', '=', partner.id)], limit=1)
                if not parent:
                    relationship = request.env['op.parent.relationship'].sudo().search(
                        [], limit=1)
                    parent = request.env['op.parent'].sudo().create({
                        'name': partner.id,
                        'email': kw.get('email'),
                        'mobile': kw.get('mobile'),
                        'relationship_id': relationship.id if relationship else False,
                    })
                if kw.get('rte_category'):
                    parent.write({'rte_category': kw.get('rte_category')})

                admission_vals = {
                    'name': '%s %s' % (kw.get('first_name'), kw.get('last_name')),
                    'first_name': kw.get('first_name'),
                    'last_name': kw.get('last_name'),
                    'birth_date': kw.get('birth_date'),
                    'email': kw.get('email'),
                    'mobile': kw.get('mobile'),
                    'gender': kw.get('gender') or 'm',
                    'course_id': choice_ids[0],
                    'register_id': register.id if register else False,
                    'partner_id': partner.id,
                    'is_rte_applicant': True,
                    'application_date': fields.Datetime.now(),
                    'rte_area_type': kw.get('rte_area_type') or False,
                    'rte_ward': kw.get('rte_ward') or False,
                    'rte_urban_body': kw.get('rte_urban_body') or False,
                    'rte_village': kw.get('rte_village') or False,
                    'rte_gram_panchayat': kw.get('rte_gram_panchayat') or False,
                    'rte_aadhaar_number': kw.get('rte_aadhaar_number') or False,
                    'rte_aadhaar_enrollment_number':
                        kw.get('rte_aadhaar_enrollment_number') or False,
                    'rte_religion': kw.get('rte_religion') or False,
                    'rte_caste_category': kw.get('rte_caste_category') or False,
                    'rte_cwsn_category': kw.get('rte_cwsn_category') or False,
                    'rte_father_aadhaar': kw.get('rte_father_aadhaar') or False,
                    'rte_mother_aadhaar': kw.get('rte_mother_aadhaar') or False,
                    'rte_guardian_aadhaar': kw.get('rte_guardian_aadhaar') or False,
                    'rte_pincode': kw.get('rte_pincode') or False,
                    'rte_block': kw.get('rte_block') or False,
                    'rte_district': kw.get('rte_district') or False,
                    'rte_preference_ids': [
                        (0, 0, {'course_id': course_id, 'sequence': (idx + 1) * 10})
                        for idx, course_id in enumerate(choice_ids)
                    ],
                }
                admission = request.env['op.admission'].sudo().create(admission_vals)
                return request.redirect('/my/rte/applications?created=%s' % admission.id)

        return request.render('bxi_rte_admission.portal_rte_apply_form', {
            'courses': courses,
            'error': error,
            'kw': kw,
            'max_choices': range(1, MAX_SCHOOL_CHOICES + 1),
        })
