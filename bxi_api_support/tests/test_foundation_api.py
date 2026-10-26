# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64

from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase

# 1x1 transparent PNG
PNG_PIXEL = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')


@tagged('post_install', '-at_install')
class TestBxiApiSupportFoundation(ApiSupportHttpCase):
    """Master lookups, profiles and the notification inbox/devices."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.class_a, cls.section_a = cls._create_class('FNDA')
        cls.class_b, cls.section_b = cls._create_class('FNDB')
        cls.parent_user = mail_new_test_user(
            cls.env, login='fnd_parent', groups='base.group_portal', password='ParentPass1!')
        cls.other_parent_user = mail_new_test_user(
            cls.env, login='fnd_other_parent', groups='base.group_portal', password='OtherPass1!')
        cls.teacher_user = mail_new_test_user(
            cls.env, login='fnd_teacher', groups='base.group_user,openeducat_core.group_op_faculty',
            password='TeacherPass1!')
        cls.child = cls._create_student('FND-001', first_name='Fnd', last_name='Child')
        cls._enroll(cls.child, cls.class_a, cls.section_a)
        cls.other_child = cls._create_student('FND-002', first_name='Other', last_name='Child')
        cls._enroll(cls.other_child, cls.class_b, cls.section_b)
        cls.parent = cls._create_parent(cls.parent_user, cls.child, mobile='9811122233')
        cls._create_parent(cls.other_parent_user, cls.other_child)
        cls.faculty = cls._create_faculty(cls.teacher_user, first_name='Fnd')
        cls.section_a.class_teacher_id = cls.faculty

    def _parent_headers(self):
        return self._headers('fnd_parent', 'ParentPass1!')

    # -- masters --------------------------------------------------------------

    def test_masters_list_hides_staff_only_lists_from_families(self):
        names = self.url_open('/api/v1/masters', headers=self._parent_headers()).json()['data']['masters']
        self.assertIn('classes', names)
        self.assertNotIn('payment-journals', names)
        resp = self.url_open('/api/v1/masters/payment-journals', headers=self._parent_headers())
        self.assertEqual(resp.status_code, 403)
        staff = self.url_open('/api/v1/masters/payment-journals', headers=self._headers('fnd_teacher', 'TeacherPass1!'))
        self.assertEqual(staff.status_code, 200)

    def test_masters_sections_filtered_by_class(self):
        resp = self.url_open(
            f'/api/v1/masters/sections?course_id={self.class_a.id}', headers=self._parent_headers())
        items = resp.json()['data']['items']
        self.assertEqual([i['id'] for i in items], self.section_a.ids)
        self.assertEqual(items[0]['course_id'], {'id': self.class_a.id, 'name': self.class_a.display_name})

    def test_masters_subjects_filtered_by_class(self):
        subject = self.env['op.subject'].create({'name': 'Fnd Physics', 'code': 'FNDPHY'})
        self.class_a.subject_ids = [(4, subject.id)]
        items = self.url_open(
            f'/api/v1/masters/subjects?course_id={self.class_a.id}', headers=self._parent_headers()).json()['data']['items']
        self.assertEqual([i['id'] for i in items], subject.ids)

    def test_unknown_master_404(self):
        self.assertEqual(self.url_open('/api/v1/masters/nope', headers=self._parent_headers()).status_code, 404)

    # -- profile ----------------------------------------------------------------

    def test_my_children_lists_only_linked_students(self):
        children = self.url_open('/api/v1/me/children', headers=self._parent_headers()).json()['data']['children']
        self.assertEqual([c['id'] for c in children], self.child.ids)
        self.assertEqual(children[0]['class']['id'], self.class_a.id)
        self.assertEqual(children[0]['section']['id'], self.section_a.id)

    def test_student_profile_access(self):
        own = self.url_open(f'/api/v1/students/{self.child.id}/profile', headers=self._parent_headers())
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.json()['data']['parents'][0]['id'], self.parent.id)
        other = self.url_open(f'/api/v1/students/{self.other_child.id}/profile', headers=self._parent_headers())
        self.assertEqual(other.status_code, 403)
        teacher = self._headers('fnd_teacher', 'TeacherPass1!')
        self.assertEqual(
            self.url_open(f'/api/v1/students/{self.child.id}/profile', headers=teacher).status_code, 200)
        self.assertEqual(
            self.url_open(f'/api/v1/students/{self.other_child.id}/profile', headers=teacher).status_code, 403)

    def test_profile_update_contact_fields_only(self):
        headers = self._parent_headers()
        bad = self.url_open('/api/v1/me/profile/update', headers=headers, json={'name': 'Hacker'})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()['error']['code'], 'invalid_field')
        ok = self.url_open('/api/v1/me/profile/update', headers=headers, json={
            'phone': '9800000001', 'city': 'Dubai'})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()['data']['contact']['city'], 'Dubai')
        self.assertEqual(self.parent.mobile, '9800000001')

    def test_avatar_upload_and_download(self):
        headers = self._parent_headers()
        self.assertEqual(self.url_open('/api/v1/me/avatar', headers=headers).status_code, 404)
        not_image = self.url_open('/api/v1/me/avatar', headers=headers, json={
            'attachments': [{'name': 'x.txt', 'data': base64.b64encode(b'hello').decode()}]})
        self.assertEqual(not_image.status_code, 400)
        upload = self.url_open('/api/v1/me/avatar', headers=headers, json={
            'attachments': [{'name': 'me.png', 'data': base64.b64encode(PNG_PIXEL).decode()}]})
        self.assertEqual(upload.status_code, 200)
        download = self.url_open('/api/v1/me/avatar', headers=headers)
        self.assertEqual(download.status_code, 200)
        self.assertTrue(download.headers['Content-Type'].startswith('image/'))

    def test_teacher_profile(self):
        data = self.url_open('/api/v1/teachers/me', headers=self._headers('fnd_teacher', 'TeacherPass1!')).json()['data']
        self.assertEqual(data['id'], self.faculty.id)
        self.assertEqual(data['class_teacher_of'][0]['section']['id'], self.section_a.id)
        self.assertEqual(self.url_open('/api/v1/teachers/me', headers=self._parent_headers()).status_code, 404)

    # -- devices & inbox ------------------------------------------------------

    def test_device_register_and_unregister(self):
        headers = self._parent_headers()
        resp = self.url_open('/api/v1/devices/register', headers=headers, json={
            'fcm_token': 'fnd-token-1', 'platform': 'ios', 'device_name': 'iPhone'})
        self.assertEqual(resp.status_code, 200)
        device = self.env['bxi.api.device'].search([('fcm_token', '=', 'fnd-token-1')])
        self.assertEqual(device.user_id, self.parent_user)
        bad = self.url_open('/api/v1/devices/register', headers=headers, json={'fcm_token': 'x', 'platform': 'nokia'})
        self.assertEqual(bad.status_code, 400)
        self.url_open('/api/v1/devices/unregister', headers=headers, json={'fcm_token': 'fnd-token-1'})
        self.assertFalse(device.active)

    def test_inbox_is_per_user_and_read_flags(self):
        Notification = self.env['bxi.notification']
        mine = Notification._notify(self.parent_user, 'Fee due', 'Pay by Friday', category='fee_due', push=False)
        Notification._notify(self.other_parent_user, 'Not yours', push=False)
        headers = self._parent_headers()
        listing = self.url_open('/api/v1/notifications', headers=headers).json()
        self.assertEqual([n['id'] for n in listing['data']['notifications']], mine.ids)
        self.assertEqual(listing['meta']['unread'], 1)

        others = Notification.search([('user_id', '=', self.other_parent_user.id)])
        self.assertEqual(
            self.url_open(f'/api/v1/notifications/{others.id}/read', headers=headers, method='POST').status_code, 404)
        read = self.url_open(f'/api/v1/notifications/{mine.id}/read', headers=headers, method='POST')
        self.assertTrue(read.json()['data']['is_read'])
        self.assertEqual(
            self.url_open('/api/v1/notifications/unread-count', headers=headers).json()['data']['unread'], 0)

        Notification._notify(self.parent_user, 'Another', push=False)
        all_read = self.url_open('/api/v1/notifications/read-all', headers=headers, method='POST')
        self.assertEqual(all_read.json()['data']['marked_read'], 1)
