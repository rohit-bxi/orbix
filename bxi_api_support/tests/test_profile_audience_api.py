# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportProfileAudience(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.class_a, cls.section_a = cls._create_class('AUDA')
        cls.class_b, cls.section_b = cls._create_class('AUDB')
        cls.student_user = mail_new_test_user(
            cls.env, login='aud_student', groups='base.group_portal', password='StudentPass1!')
        cls.parent_user = mail_new_test_user(
            cls.env, login='aud_parent', groups='base.group_portal', password='ParentPass1!')
        cls.teacher_user = mail_new_test_user(
            cls.env, login='aud_teacher', groups='base.group_user,openeducat_core.group_op_faculty',
            password='TeacherPass1!')
        cls.manager_user = mail_new_test_user(
            cls.env, login='aud_manager',
            groups='base.group_user,bxi_school_announcement.group_announcement_manager,'
                   'bxi_school_notice.group_notice_manager',
            password='ManagerPass1!')
        cls.student = cls._create_student('AUD-001', user=cls.student_user)
        cls._enroll(cls.student, cls.class_a, cls.section_a)
        cls.parent = cls._create_parent(cls.parent_user, cls.student, mobile='+91 90000-11122')
        cls.faculty = cls._create_faculty(cls.teacher_user, first_name='Aud')
        cls.section_b.class_teacher_id = cls.faculty

        Announcement = cls.env['bxi.announcement']
        cls.ann = {}
        for key, vals in {
            'everyone': {'target_audience': 'everyone'},
            'students': {'target_audience': 'all_students'},
            'parents': {'target_audience': 'all_parents'},
            'teachers': {'target_audience': 'all_teachers'},
            'class_a': {'target_audience': 'specific_class', 'course_ids': [(6, 0, cls.class_a.ids)]},
            'class_b': {'target_audience': 'specific_class', 'course_ids': [(6, 0, cls.class_b.ids)]},
        }.items():
            announcement = Announcement.create(dict(vals, title=f'Aud {key}', body='Body'))
            announcement.action_publish()
            cls.ann[key] = announcement

    def _visible_announcements(self, login, password):
        resp = self.url_open('/api/v1/announcements?limit=200', headers=self._headers(login, password))
        ids = {a['id'] for a in resp.json()['data']['announcements']}
        return {key for key, ann in self.ann.items() if ann.id in ids}

    # -- /auth/me -----------------------------------------------------------

    def test_me_for_parent_lists_role_and_children(self):
        data = self.url_open('/api/v1/auth/me', headers=self._headers('aud_parent', 'ParentPass1!')).json()['data']
        self.assertIn('parent', data['roles'])
        self.assertNotIn('staff', data['roles'])
        self.assertEqual(data['parent_id'], self.parent.id)
        self.assertEqual(data['student_ids'], self.student.ids)
        self.assertFalse(data['permissions']['fee_staff'])

    def test_me_for_student_and_teacher(self):
        student = self.url_open('/api/v1/auth/me', headers=self._headers('aud_student', 'StudentPass1!')).json()['data']
        self.assertEqual(student['roles'], ['student'])
        self.assertEqual(student['student_id'], self.student.id)
        teacher = self.url_open('/api/v1/auth/me', headers=self._headers('aud_teacher', 'TeacherPass1!')).json()['data']
        self.assertIn('teacher', teacher['roles'])
        self.assertIn('staff', teacher['roles'])
        self.assertEqual(teacher['faculty_id'], self.faculty.id)

    # -- announcement audience --------------------------------------------------

    def test_parent_sees_only_family_announcements(self):
        self.assertEqual(
            self._visible_announcements('aud_parent', 'ParentPass1!'), {'everyone', 'parents', 'class_a'})

    def test_student_sees_only_student_announcements(self):
        self.assertEqual(
            self._visible_announcements('aud_student', 'StudentPass1!'), {'everyone', 'students', 'class_a'})

    def test_teacher_sees_staff_and_taught_class_announcements(self):
        self.assertEqual(
            self._visible_announcements('aud_teacher', 'TeacherPass1!'), {'everyone', 'teachers', 'class_b'})

    def test_manager_sees_everything(self):
        self.assertEqual(self._visible_announcements('aud_manager', 'ManagerPass1!'), set(self.ann))

    def test_parent_cannot_open_staff_announcement_by_id(self):
        headers = self._headers('aud_parent', 'ParentPass1!')
        self.assertEqual(
            self.url_open(f"/api/v1/announcements/{self.ann['teachers'].id}", headers=headers).status_code, 403)
        self.assertEqual(
            self.url_open(f"/api/v1/announcements/{self.ann['parents'].id}", headers=headers).status_code, 200)

    # -- notice audience --------------------------------------------------------

    def test_notice_audience_and_expiry(self):
        Notice = self.env['bxi.notice']
        staff_notice = Notice.create({'title': 'Staff only', 'body': 'x', 'target_audience': 'all_teachers'})
        family_notice = Notice.create({'title': 'Families', 'body': 'x', 'target_audience': 'students_and_families'})
        expired_notice = Notice.create({
            'title': 'Old', 'body': 'x', 'target_audience': 'all_parents', 'expires_on': '2020-01-01'})
        headers = self._headers('aud_parent', 'ParentPass1!')
        ids = {n['id'] for n in self.url_open('/api/v1/notices?limit=200', headers=headers).json()['data']['notices']}
        self.assertIn(family_notice.id, ids)
        self.assertNotIn(staff_notice.id, ids)
        self.assertNotIn(expired_notice.id, ids)
        self.assertEqual(self.url_open(f'/api/v1/notices/{staff_notice.id}', headers=headers).status_code, 403)

    # -- phone lookup (OTP login) ---------------------------------------------

    def test_parent_found_by_op_parent_mobile(self):
        users = self.env['res.users']._bxi_find_users_by_phone('9000011122')
        self.assertEqual(users, self.parent_user)
        self.assertEqual(self.parent_user._bxi_get_otp_phone(), '+91 90000-11122')
