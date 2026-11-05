# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .common import FaceHttpCase, photo


def _frames(person, yaws=(0.0, 0.2, -0.2)):
    return [{'image': photo(person, yaw)} for yaw in yaws]


@tagged('post_install', '-at_install')
class TestFaceEnrolment(FaceHttpCase):

    def test_self_enrolment_is_pending_until_approved(self):
        headers = self.headers('face_teacher', 'TeacherPass1!')
        resp = self.url_open('/api/v1/face/enroll', headers=headers, json={'consent': True, 'frames': _frames('tara')})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertEqual(data['state'], 'pending')
        enrolment = self.env['bxi.face.enrolment'].browse(data['enrolment_id'])
        self.assertEqual(enrolment.source, 'self')
        self.assertEqual(enrolment.consent_by_id, self.teacher_user)
        self.assertEqual(len(enrolment.template_ids), 3)
        # Pending faces can't log in.
        self.assertEqual(self.face_login('tara', login_hint='face_teacher').status_code, 401)
        # Managers are told there is something to review.
        self.assertTrue(self.env['bxi.notification'].sudo().search([
            ('user_id', '=', self.manager_user.id), ('res_model', '=', 'bxi.face.enrolment')]))

    def test_face_data_is_encrypted_and_separate_from_avatar(self):
        avatar_before = self.teacher_user.partner_id.image_1920
        headers = self.headers('face_teacher', 'TeacherPass1!')
        data = self.url_open('/api/v1/face/enroll', headers=headers,
                             json={'consent': True, 'frames': _frames('tara')}).json()['data']
        template = self.env['bxi.face.enrolment'].browse(data['enrolment_id']).template_ids[0]
        self.assertTrue(template.sudo().embedding_enc.startswith('gAAAA'))   # Fernet token
        self.assertEqual(template._get_embedding().shape, (128,))
        self.assertTrue(template._get_image().startswith(b'\xff\xd8'))
        self.assertEqual(self.teacher_user.partner_id.image_1920, avatar_before)

    def test_consent_required_for_adults(self):
        headers = self.headers('face_teacher', 'TeacherPass1!')
        resp = self.url_open('/api/v1/face/enroll', headers=headers, json={'frames': _frames('tara')})
        self.assertEqual(resp.json()['error']['code'], 'consent_required')

    def test_photo_rules(self):
        headers = self.headers('face_teacher', 'TeacherPass1!')
        cases = [
            (_frames('tara', (0.0, 0.2)), 'invalid_frames'),
            (_frames('tara', (0.4, 0.3, -0.4)), 'no_frontal_face'),
            ([{'image': photo('tara')}, {'image': photo('tara', 0.2)}, {'image': photo('mallory', -0.2)}],
             'inconsistent_faces'),
            ([{'image': photo('tara')}, {'image': photo(error='multiple_faces')}, {'image': photo('tara')}],
             'multiple_faces'),
        ]
        for frames, code in cases:
            resp = self.url_open('/api/v1/face/enroll', headers=headers, json={'consent': True, 'frames': frames})
            self.assertEqual(resp.status_code, 400, code)
            self.assertEqual(resp.json()['error']['code'], code)

    def test_enrolment_needs_recent_confirmation(self):
        self.enrol(self.teacher_user, 'tara')
        token = self.face_login('tara', login_hint='face_teacher').json()['data']['token']
        headers = {'Authorization': f'Bearer {token}'}
        resp = self.url_open('/api/v1/face/enroll', headers=headers, json={'consent': True, 'frames': _frames('tara')})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['error']['code'], 'step_up_required')

        # An old password session must confirm again too.
        headers = self.headers('face_teacher', 'TeacherPass1!')
        token = self.token_record(headers['Authorization'][7:])
        token.verified_until = fields.Datetime.now() - timedelta(minutes=1)
        resp = self.url_open('/api/v1/face/enroll', headers=headers, json={'consent': True, 'frames': _frames('tara')})
        self.assertEqual(resp.status_code, 403)
        self.url_open('/api/v1/auth/step-up', headers=headers, json={'password': 'TeacherPass1!'})
        resp = self.url_open('/api/v1/face/enroll', headers=headers, json={'consent': True, 'frames': _frames('tara')})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_new_submission_replaces_pending_one(self):
        headers = self.headers('face_teacher', 'TeacherPass1!')
        first = self.url_open('/api/v1/face/enroll', headers=headers,
                              json={'consent': True, 'frames': _frames('tara')}).json()['data']['enrolment_id']
        self.url_open('/api/v1/face/enroll', headers=headers, json={'consent': True, 'frames': _frames('tara')})
        first = self.env['bxi.face.enrolment'].browse(first)
        self.assertEqual(first.state, 'revoked')
        self.assertFalse(first.template_ids)

    # -- parents and children ----------------------------------------------------------------

    def test_parent_enrols_child_with_consent(self):
        headers = self.headers('face_parent', 'ParentPass1!')
        resp = self.url_open('/api/v1/face/enroll', headers=headers, json={
            'student_id': self.student.id, 'consent': True, 'frames': _frames('sam')})
        self.assertEqual(resp.status_code, 200, resp.text)
        enrolment = self.env['bxi.face.enrolment'].browse(resp.json()['data']['enrolment_id'])
        self.assertEqual(enrolment.user_id, self.student_user)
        self.assertEqual(enrolment.source, 'parent')
        self.assertEqual(enrolment.student_id, self.student)
        consent = self.env['bxi.face.service']._active_consent(self.student)
        self.assertEqual(consent.granted_by_id, self.parent_user)

    def test_parent_cannot_enrol_without_consent_or_for_other_child(self):
        headers = self.headers('face_parent', 'ParentPass1!')
        resp = self.url_open('/api/v1/face/enroll', headers=headers, json={
            'student_id': self.student.id, 'frames': _frames('sam')})
        self.assertEqual(resp.json()['error']['code'], 'consent_required')
        resp = self.url_open('/api/v1/face/enroll', headers=headers, json={
            'student_id': self.other_student.id, 'consent': True, 'frames': _frames('olga')})
        self.assertEqual(resp.status_code, 403)

    def test_student_self_enrolment_needs_parent_consent(self):
        headers = self.headers('face_student', 'StudentPass1!')
        body = {'consent': True, 'frames': _frames('sam')}
        self.assertEqual(self.url_open('/api/v1/face/enroll', headers=headers, json=body)
                         .json()['error']['code'], 'consent_required')
        self.consent()
        resp = self.url_open('/api/v1/face/enroll', headers=headers, json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        enrolment = self.env['bxi.face.enrolment'].browse(resp.json()['data']['enrolment_id'])
        self.assertEqual(enrolment.consent_by_id, self.parent_user)

    def test_child_without_app_account(self):
        self.student.user_id = False
        resp = self.url_open('/api/v1/face/enroll', headers=self.headers('face_parent', 'ParentPass1!'), json={
            'student_id': self.student.id, 'consent': True, 'frames': _frames('sam')})
        self.assertEqual(resp.json()['error']['code'], 'student_has_no_account')

    def test_consent_endpoint_grant_and_withdraw(self):
        headers = self.headers('face_parent', 'ParentPass1!')
        resp = self.url_open('/api/v1/face/consent', headers=headers, json={'student_id': self.student.id, 'granted': True})
        self.assertTrue(resp.json()['data']['consent']['granted'])
        enrolment = self.enrol(self.student_user, 'sam')
        resp = self.url_open('/api/v1/face/consent', headers=headers, json={'student_id': self.student.id, 'granted': False})
        self.assertFalse(resp.json()['data']['consent']['granted'])
        self.assertEqual(enrolment.state, 'revoked')
        resp = self.url_open('/api/v1/face/consent', headers=self.headers('face_other_parent', 'OtherPass1!'),
                             json={'student_id': self.student.id, 'granted': True})
        self.assertEqual(resp.status_code, 403)

    def test_status_for_parent_lists_children(self):
        self.consent()
        self.enrol(self.student_user, 'sam')
        resp = self.url_open('/api/v1/face/status', headers=self.headers('face_parent', 'ParentPass1!'))
        data = resp.json()['data']
        self.assertTrue(data['face_login_enabled'])
        self.assertEqual(data['self']['state'], 'none')
        child = data['children'][0]
        self.assertEqual(child['student_id'], self.student.id)
        self.assertEqual(child['state'], 'active')
        self.assertTrue(child['can_use_face_login'])
        self.assertTrue(child['consent']['granted'])
        self.assertIsNotNone(child['expires_at'])   # students re-enrol yearly

    def test_disable_deletes_face_data(self):
        enrolment = self.enrol(self.teacher_user, 'tara')
        resp = self.url_open('/api/v1/face/disable', headers=self.headers('face_teacher', 'TeacherPass1!'), json={}, method='POST')
        self.assertEqual(resp.json()['data']['state'], 'none')
        self.assertEqual(enrolment.state, 'revoked')
        self.assertFalse(enrolment.template_ids)
        self.assertEqual(self.face_login('tara', login_hint='face_teacher').status_code, 401)

    def test_parent_disables_child(self):
        self.consent()
        enrolment = self.enrol(self.student_user, 'sam')
        self.url_open('/api/v1/face/disable', headers=self.headers('face_parent', 'ParentPass1!'),
                      json={'student_id': self.student.id})
        self.assertEqual(enrolment.state, 'revoked')

    # -- lifecycle -------------------------------------------------------------------------------

    def test_cron_expires_student_enrolments_and_cleans_up(self):
        self.consent()
        enrolment = self.enrol(self.student_user, 'sam')
        enrolment.expires_at = fields.Datetime.now() - timedelta(days=1)
        teacher_enrolment = self.enrol(self.teacher_user, 'tara')
        self.teacher_user.active = False
        self.env['bxi.face.enrolment']._cron_maintenance()
        self.assertEqual(enrolment.state, 'expired')
        self.assertFalse(enrolment.template_ids)
        self.assertEqual(teacher_enrolment.state, 'revoked')

    def test_newer_approval_supersedes_older(self):
        first = self.enrol(self.teacher_user, 'tara')
        second = self.enrol(self.teacher_user, 'tara')
        self.assertEqual(first.state, 'revoked')
        self.assertEqual(second.state, 'active')

    def test_approval_marks_identity_photo_verified(self):
        self.enrol(self.parent_user, 'pat')
        self.assertEqual(self.parent.face_verification_status, 'verified')
