# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import FaceHttpCase, photo


@tagged('post_install', '-at_install')
class TestFacePeopleManagement(FaceHttpCase):
    """The "face" block of the office's teacher/student/parent screens
    (bxi_api_support people endpoints) enrols in person, like
    /api/v1/admin/face/enrol."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.office_user = mail_new_test_user(
            cls.env, login='face_office', password='OfficePass1!',
            groups='base.group_user,openeducat_core.group_op_back_office_admin')

    def _office(self):
        return self.headers('face_office', 'OfficePass1!')

    def test_teacher_created_with_face(self):
        resp = self.url_open('/api/v1/teachers', headers=self._office(), json={
            'first_name': 'Nia', 'last_name': 'New', 'gender': 'female', 'birth_date': '1990-01-01',
            'account': {'username': 'nia.new', 'password': 'NiaPass1234'},
            'face': {'enabled': True, 'image': photo('nia')}})
        self.assertEqual(resp.status_code, 201, resp.text)
        face = resp.json()['data']['face']
        self.assertEqual(face['state'], 'active')
        faculty = self.env['op.faculty'].browse(resp.json()['data']['id'])
        self.assertEqual(faculty.face_verification_status, 'verified')
        enrolment = self.env['bxi.face.enrolment'].search([('user_id', '=', faculty.user_id.id)])
        self.assertEqual(enrolment.source, 'staff')
        self.assertEqual(enrolment.submitted_by_id, self.office_user)

        off = self.url_open('/api/v1/teachers/%s/face' % faculty.id, headers=self._office(),
                            json={'enabled': False})
        self.assertEqual(off.json()['data']['face']['state'], 'none')
        again = self.url_open('/api/v1/teachers/%s/face' % faculty.id, headers=self._office(),
                              json={'enabled': True})
        self.assertEqual(again.json()['error']['code'], 'missing_face_image')

    def test_bad_photo_rolls_back_the_create(self):
        resp = self.url_open('/api/v1/teachers', headers=self._office(), json={
            'first_name': 'Bad', 'last_name': 'Photo', 'gender': 'male', 'birth_date': '1990-01-01',
            'account': {'username': 'bad.photo'}, 'face': {'enabled': True, 'image': photo(error='no_face')}})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'no_face')
        self.assertFalse(self.env['res.users'].search([('login', '=', 'bad.photo')]))
        self.assertFalse(self.env['op.faculty'].search([('last_name', '=', 'Photo')]))

    def test_student_face_needs_parent_consent(self):
        url = '/api/v1/students/%s/update' % self.student.id
        resp = self.url_open(url, headers=self._office(), json={'face': {'enabled': True, 'image': photo('sam')}})
        self.assertEqual(resp.json()['error']['code'], 'consent_required')
        resp = self.url_open(url, headers=self._office(), json={
            'face': {'enabled': True, 'image': photo('sam'), 'consent_reference': 'Form 7'}})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['face']['state'], 'active')
        self.assertEqual(self.env['bxi.face.service']._active_consent(self.student).reference, 'Form 7')
