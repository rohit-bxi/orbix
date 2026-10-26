# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import api, models

COORDINATOR_GROUPS = (
    'bxi_academic_management.group_academic_coordinator',
    'bxi_academic_management.group_academic_manager',
)
FACULTY_GROUP = 'openeducat_core.group_op_faculty'

# permission flag -> groups that grant it. Returned on /auth/me so the app
# can show or hide staff screens without guessing from group names; every
# route still does its own check server-side.
PERMISSION_GROUPS = {
    'academic_coordinator': COORDINATOR_GROUPS,
    'fee_staff': ('openeducat_fees.group_openeducat_fees_user', 'openeducat_fees.group_op_fees_admin'),
    'exemption_staff': ('bxi_fee_exemption_management.group_exemption_staff',
                        'bxi_fee_exemption_management.group_exemption_manager'),
    'refund_staff': ('bxi_student_refund_management.group_refund_staff',
                     'bxi_student_refund_management.group_refund_manager'),
    'scholarship_staff': ('bxi_school_scholarship.group_scholarship_staff',
                          'bxi_school_scholarship.group_scholarship_manager'),
    'announcement_manager': ('bxi_school_announcement.group_announcement_manager',),
    'notice_manager': ('bxi_school_notice.group_notice_manager',),
    'certificate_manager': ('bxi_certificate_management.group_certificate_user',
                            'bxi_certificate_management.group_certificate_manager'),
    'timetable_coordinator': ('bxi_class_timetable_inhencement.group_class_timetable_coordinator',
                              'bxi_class_timetable_inhencement.group_class_timetable_manager'),
    'rte_staff': ('bxi_rte_admission.group_rte_school_coordinator', 'bxi_rte_admission.group_rte_admin',
                  'bxi_rte_admission.group_rte_district_officer'),
    'admission_staff': ('openeducat_admission.group_op_admission_user', 'openeducat_admission.group_op_admission_admin'),
    'exam_staff': ('openeducat_exam.group_op_exam_user', 'openeducat_exam.group_op_exam_admin'),
    'library_staff': ('openeducat_library.group_op_library_user', 'openeducat_library.group_op_library',
                      'bxi_library_book_request.group_book_request_librarian'),
    'canteen_staff': ('bxi_school_canteen_management.group_canteen_staff',
                      'bxi_school_canteen_management.group_canteen_manager'),
    'uniform_staff': ('bxi_uniform_management.group_uniform_staff', 'bxi_uniform_management.group_uniform_manager'),
    'transport_staff': ('bxi_school_transport_bus_management.group_transport_staff',
                        'bxi_school_transport_bus_management.group_transport_manager'),
    'health_staff': ('op_health_center.group_health_staff', 'op_health_center.group_health_manager'),
    'lab_staff': ('op_student_lab_management.group_lab_instructor', 'op_student_lab_management.group_lab_admin'),
    'event_coordinator': ('bxi_school_event_management.group_school_event_coordinator',),
    'visitor_staff': ('visitor_management.group_visitor_officer', 'visitor_management.group_visitor_management'),
    'leave_approver': ('hr_holidays.group_hr_holidays_responsible', 'hr_holidays.group_hr_holidays_user'),
}


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _bxi_has_any_group(self, groups):
        self.ensure_one()
        return any(self.has_group(group) for group in groups)

    def _bxi_school_context(self):
        """Who this user is in the school, as records (all sudo): their own
        student/parent/teacher record, the students they may act for (self
        and/or children), and the classes/sections those students are in
        or - for a teacher - teaches. The single source for /auth/me, the
        audience filters on feeds and the family/teacher scoping helpers.
        """
        self.ensure_one()
        env = self.env
        student = env['op.student'].sudo().search([('user_id', '=', self.id)], limit=1)
        parent = env['op.parent'].sudo().search([('user_id', '=', self.id)], limit=1)
        faculty = env['op.faculty'].sudo().search([('user_id', '=', self.id)], limit=1)
        students = student | parent.student_ids
        enrollments = students.course_detail_ids.filtered(lambda line: line.state == 'running')
        teaching_lines = env['bxi.timetable.line'].sudo().search([('teacher_id', '=', faculty.id)]) if faculty else []
        class_teacher_batches = env['op.batch'].sudo().search([('class_teacher_id', '=', faculty.id)]) if faculty else env['op.batch']
        teaching_batches = (teaching_lines and teaching_lines.timetable_id.batch_id or env['op.batch']) | class_teacher_batches
        teaching_courses = (teaching_lines and teaching_lines.timetable_id.course_id or env['op.course']) | class_teacher_batches.course_id
        return {
            'student': student,
            'parent': parent,
            'faculty': faculty,
            'students': students,
            'family_courses': enrollments.course_id,
            'family_batches': enrollments.batch_id,
            'teaching_courses': teaching_courses,
            'teaching_batches': teaching_batches,
        }

    def _bxi_is_teacher(self, context=None):
        context = context or self._bxi_school_context()
        return bool(context['faculty']) or self.has_group(FACULTY_GROUP)

    def _bxi_is_staff(self, context=None):
        """A school employee, as opposed to a family login. Students and
        parents are often plain internal users in this deployment, so
        base.group_user alone can't tell them apart: a user only counts as
        staff if they teach, hold a staff group, or have no family link."""
        self.ensure_one()
        if not self.has_group('base.group_user'):
            return False
        context = context or self._bxi_school_context()
        if self._bxi_is_teacher(context) or self.has_group('base.group_system'):
            return True
        if any(self._bxi_has_any_group(groups) for groups in PERMISSION_GROUPS.values()):
            return True
        return not (context['student'] or context['parent'])

    def _bxi_roles(self, context=None):
        context = context or self._bxi_school_context()
        roles = []
        if context['student']:
            roles.append('student')
        if context['parent']:
            roles.append('parent')
        if self._bxi_is_teacher(context):
            roles.append('teacher')
        if self._bxi_has_any_group(COORDINATOR_GROUPS):
            roles.append('coordinator')
        if self._bxi_is_staff(context):
            roles.append('staff')
        if self.has_group('base.group_system'):
            roles.append('admin')
        return roles

    def _get_bxi_api_profile(self):
        profile = super()._get_bxi_api_profile()
        context = self._bxi_school_context()
        profile.update({
            'roles': self._bxi_roles(context),
            'student_id': context['student'].id or None,
            'parent_id': context['parent'].id or None,
            'faculty_id': context['faculty'].id or None,
            'student_ids': context['students'].ids,
            'permissions': {
                flag: self._bxi_has_any_group(groups) for flag, groups in PERMISSION_GROUPS.items()
            },
        })
        return profile

    @api.model
    def _bxi_find_users_by_phone(self, phone):
        users = super()._bxi_find_users_by_phone(phone)
        parent_ids = self._bxi_partner_ids_with_phone('op_parent', 'mobile', phone)
        if parent_ids:
            users |= self.env['op.parent'].sudo().browse(parent_ids).user_id.filtered('active')
        return users

    def _bxi_get_otp_phone(self):
        phone = super()._bxi_get_otp_phone()
        if phone:
            return phone
        return self.env['op.parent'].sudo().search([('user_id', '=', self.id)], limit=1).mobile
