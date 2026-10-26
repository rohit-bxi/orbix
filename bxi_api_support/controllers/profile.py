# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64

import pytz

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools.mimetypes import guess_mimetype

from odoo.addons.bxi_api.controllers.auth import (
    api_error, api_file_response, api_response, parse_request, require_auth,
)

from .common import can_view_student, date_str, ref, running_enrollment, school_context

PARTNER_UPDATE_FIELDS = ('email', 'phone', 'street', 'street2', 'city', 'zip', 'state_id', 'country_id')
USER_UPDATE_FIELDS = ('lang', 'tz')


def student_summary(student):
    enrollment = running_enrollment(student)
    return {
        'id': student.id,
        'name': student.name,
        'gr_no': student.gr_no or None,
        'roll_number': enrollment.roll_number or None,
        'class': ref(enrollment.course_id),
        'section': ref(enrollment.batch_id),
        'gender': student.gender,
        'birth_date': date_str(student.birth_date),
        'has_photo': bool(student.image_128),
    }


def _student_detail(student):
    data = student_summary(student)
    parents = request.env['op.parent'].sudo().search([('student_ids', 'in', student.id)])
    data.update({
        'email': student.email or None,
        'phone': student.phone or None,
        'blood_group': student.blood_group or None,
        'nationality': ref(student.nationality),
        'admission_date': date_str(student.admission_date),
        'is_allergy': student.is_allergy,
        'allergy': student.allergy or None,
        'address': {
            'street': student.street or None, 'street2': student.street2 or None, 'city': student.city or None,
            'zip': student.zip or None, 'state': ref(student.state_id), 'country': ref(student.country_id),
        },
        'enrollments': [{
            'class': ref(line.course_id),
            'section': ref(line.batch_id),
            'roll_number': line.roll_number or None,
            'academic_year': ref(line.academic_years_id),
            'state': line.state,
        } for line in student.course_detail_ids],
        'parents': [{
            'id': parent.id,
            'name': parent.name.name,
            'relationship': ref(parent.relationship_id),
            'mobile': parent.mobile or None,
            'email': parent.email or parent.name.email or None,
        } for parent in parents],
    })
    return data


def _image_response(image_b64, filename):
    if not image_b64:
        return api_error('No photo on file.', status=404, code='no_photo')
    content = base64.b64decode(image_b64)
    return api_file_response(content, filename, guess_mimetype(content, default='image/png'))


class BxiApiSupportProfileController(http.Controller):

    @http.route('/api/v1/me/children', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def my_children(self, **kwargs):
        """The students this login acts for - a parent's children, or a
        student's own record - i.e. the valid `student_id`s for the
        family-facing endpoints."""
        context = school_context(request.env)
        return api_response({'children': [student_summary(s) for s in context['students']]})

    @http.route('/api/v1/me/profile', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def my_profile(self, **kwargs):
        user = request.env.user
        partner = user.partner_id.sudo()
        context = school_context(request.env)
        return api_response({
            'user': user._get_bxi_api_profile(),
            'contact': {
                'email': partner.email or None, 'phone': partner.phone or None,
                'street': partner.street or None, 'street2': partner.street2 or None,
                'city': partner.city or None, 'zip': partner.zip or None,
                'state': ref(partner.state_id), 'country': ref(partner.country_id),
            },
            'has_photo': bool(partner.image_128),
            'student': student_summary(context['student']) if context['student'] else None,
            'parent': {
                'id': context['parent'].id,
                'relationship': ref(context['parent'].relationship_id),
                'mobile': context['parent'].mobile or None,
            } if context['parent'] else None,
            'teacher': {'id': context['faculty'].id, 'name': context['faculty'].name} if context['faculty'] else None,
        })

    @http.route('/api/v1/me/profile/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_my_profile(self, **kwargs):
        """Contact details only - names, class and other school records are
        managed by the school office, not self-service."""
        payload = request.get_json_data() or {}
        unknown = set(payload) - set(PARTNER_UPDATE_FIELDS) - set(USER_UPDATE_FIELDS)
        if unknown:
            return api_error(
                'These fields cannot be changed here: %s.' % ', '.join(sorted(unknown)),
                status=400, code='invalid_field')
        user = request.env.user.sudo()
        if 'lang' in payload and payload['lang'] not in dict(request.env['res.lang'].get_installed()):
            return api_error('Unknown or inactive language.', status=400, code='invalid_lang')
        if 'tz' in payload and payload['tz'] and payload['tz'] not in pytz.all_timezones:
            return api_error('Unknown timezone.', status=400, code='invalid_tz')
        partner_vals = {k: payload[k] or False for k in PARTNER_UPDATE_FIELDS if k in payload}
        user_vals = {k: payload[k] or False for k in USER_UPDATE_FIELDS if k in payload}
        try:
            if partner_vals:
                user.partner_id.write(partner_vals)
            if user_vals:
                user.write(user_vals)
        except UserError as exc:
            return api_error(str(exc), status=400, code='validation_error')
        if 'phone' in partner_vals:
            # Keep the parent record's own number (used for OTP login) in step.
            parent = school_context(request.env)['parent']
            if parent:
                parent.mobile = partner_vals['phone']
        return self.my_profile()

    @http.route('/api/v1/me/avatar', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_my_avatar(self, **kwargs):
        return _image_response(request.env.user.sudo().partner_id.image_512, 'avatar.png')

    @http.route('/api/v1/me/avatar', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def set_my_avatar(self, **kwargs):
        """Multipart `file`, or JSON {"attachments": [{"data": base64}]}."""
        _payload, files, error = parse_request()
        if error:
            return error
        if not files:
            return api_error('An image file is required.', status=400, code='missing_file')
        if not guess_mimetype(files[0]['content'], default='').startswith('image/'):
            return api_error('The file must be an image.', status=400, code='invalid_image')
        try:
            request.env.user.sudo().partner_id.image_1920 = base64.b64encode(files[0]['content'])
        except UserError as exc:
            return api_error(str(exc), status=400, code='invalid_image')
        return api_response({'has_photo': True})

    @http.route('/api/v1/students/<int:student_id>/profile', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def student_profile(self, student_id, **kwargs):
        student = request.env['op.student'].sudo().browse(student_id)
        if not student.exists():
            return api_error('Student not found.', status=404, code='not_found')
        if not can_view_student(request.env, student):
            return api_error('Not authorized for this student.', status=403, code='forbidden')
        return api_response(_student_detail(student))

    @http.route('/api/v1/students/<int:student_id>/photo', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def student_photo(self, student_id, **kwargs):
        student = request.env['op.student'].sudo().browse(student_id)
        if not student.exists():
            return api_error('Student not found.', status=404, code='not_found')
        if not can_view_student(request.env, student):
            return api_error('Not authorized for this student.', status=403, code='forbidden')
        return _image_response(student.image_512, f'student-{student.id}.png')

    @http.route('/api/v1/teachers/me', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def my_teacher_profile(self, **kwargs):
        context = school_context(request.env)
        faculty = context['faculty']
        if not faculty:
            return api_error('No teacher profile is linked to this account.', status=404, code='not_found')
        lines = request.env['bxi.timetable.line'].sudo().search([('teacher_id', '=', faculty.id)])
        class_teacher_of = request.env['op.batch'].sudo().search([('class_teacher_id', '=', faculty.id)])
        return api_response({
            'id': faculty.id,
            'name': faculty.name,
            'email': faculty.email or None,
            'phone': faculty.phone or None,
            'joining_date': date_str(faculty.joining_date),
            'department': ref(faculty.main_department_id),
            'subjects': [ref(s) for s in faculty.faculty_subject_ids],
            'class_teacher_of': [{'section': ref(b), 'class': ref(b.course_id)} for b in class_teacher_of],
            'teaches': sorted({
                (line.timetable_id.course_id.id, line.timetable_id.batch_id.id, line.subject_id.id): {
                    'class': ref(line.timetable_id.course_id),
                    'section': ref(line.timetable_id.batch_id),
                    'subject': ref(line.subject_id),
                } for line in lines if line.subject_id
            }.values(), key=lambda t: (t['class']['name'], t['section']['name'], t['subject']['name'])),
            'weekly_periods': len(lines),
        })

