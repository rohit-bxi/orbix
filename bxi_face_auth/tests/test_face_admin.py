# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64

from odoo.tests import tagged

from .common import FaceHttpCase, photo


def _frames(person, yaws=(0.0, 0.2, -0.2)):
    return [{'image': photo(person, yaw)} for yaw in yaws]


@tagged('post_install', '-at_install')
class TestFaceAdmin(FaceHttpCase):

    def setUp(self):
        super().setUp()
        self.manager = self.headers('face_manager', 'ManagerPass1!')

    def _submit(self, login='face_teacher', password='TeacherPass1!', person='tara', **extra):
        resp = self.url_open('/api/v1/face/enroll', headers=self.headers(login, password),
                             json=dict(extra, consent=True, frames=_frames(person)))
        return self.env['bxi.face.enrolment'].browse(resp.json()['data']['enrolment_id'])

    def test_non_managers_are_refused(self):
        for login, password in (('face_teacher', 'TeacherPass1!'), ('face_parent', 'ParentPass1!')):
            resp = self.url_open('/api/v1/admin/face/enrolments', headers=self.headers(login, password))
            self.assertEqual(resp.status_code, 403)

    def test_review_queue_photos_and_approve(self):
        enrolment = self._submit()
        resp = self.url_open('/api/v1/admin/face/enrolments?state=pending', headers=self.manager)
        self.assertEqual(resp.status_code, 200, resp.text)
        items = resp.json()['data']
        self.assertEqual([item['id'] for item in items], [enrolment.id])
        self.assertEqual(items[0]['teacher']['id'], self.faculty.id)
        self.assertIn('teacher', items[0]['roles'])
        self.assertEqual(resp.json()['meta']['total'], 1)

        detail = self.url_open(f'/api/v1/admin/face/enrolments/{enrolment.id}', headers=self.manager).json()['data']
        self.assertEqual(len(detail['photos']), 3)
        photos = self.url_open(f'/api/v1/admin/face/enrolments/{enrolment.id}/photos', headers=self.manager).json()['data']
        self.assertTrue(base64.b64decode(photos['photos'][0]['image']).startswith(b'\xff\xd8'))

        resp = self.url_open(f'/api/v1/admin/face/enrolments/{enrolment.id}/approve', headers=self.manager, json={}, method='POST')
        self.assertEqual(resp.json()['data']['state'], 'active')
        self.assertEqual(enrolment.reviewed_by_id, self.manager_user)
        self.assertEqual(self.face_login('tara', login_hint='face_teacher').status_code, 200)
        self.assertTrue(self.env['bxi.notification'].sudo().search([
            ('user_id', '=', self.teacher_user.id), ('title', '=', 'Face login is ready')]))

    def test_role_filter(self):
        self._submit()
        resp = self.url_open('/api/v1/admin/face/enrolments?role=student', headers=self.manager)
        self.assertEqual(resp.json()['data'], [])
        resp = self.url_open('/api/v1/admin/face/enrolments?role=nope', headers=self.manager)
        self.assertEqual(resp.status_code, 400)

    def test_reject_deletes_photos(self):
        enrolment = self._submit()
        resp = self.url_open(f'/api/v1/admin/face/enrolments/{enrolment.id}/reject', headers=self.manager,
                             json={'reason': 'Too dark'})
        self.assertEqual(resp.json()['data']['state'], 'rejected')
        self.assertFalse(enrolment.template_ids)
        status = self.url_open('/api/v1/face/status', headers=self.headers('face_teacher', 'TeacherPass1!'))
        self.assertEqual(status.json()['data']['self']['state'], 'rejected')
        self.assertEqual(status.json()['data']['self']['reject_reason'], 'Too dark')
        again = self.url_open(f'/api/v1/admin/face/enrolments/{enrolment.id}/approve', headers=self.manager, json={}, method='POST')
        self.assertEqual(again.json()['error']['code'], 'invalid_state')

    def test_duplicate_face_needs_a_decision(self):
        self.enrol(self.parent_user, 'tara')   # someone already enrolled with this face
        enrolment = self._submit()
        self.assertEqual(enrolment.duplicate_user_ids, self.parent_user)
        url = f'/api/v1/admin/face/enrolments/{enrolment.id}/approve'
        resp = self.url_open(url, headers=self.manager, json={}, method='POST')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error']['duplicates'][0]['id'], self.parent_user.id)
        resp = self.url_open(url, headers=self.manager, json={'same_person_user_ids': [self.manager_user.id]})
        self.assertEqual(resp.status_code, 400)
        resp = self.url_open(url, headers=self.manager, json={'same_person_user_ids': [self.parent_user.id]})
        self.assertEqual(resp.json()['data']['state'], 'active')
        self.assertEqual(enrolment.same_person_user_ids, self.parent_user)

    def test_approval_rechecks_student_consent(self):
        self.consent()
        enrolment = self._submit('face_parent', 'ParentPass1!', 'sam', student_id=self.student.id)
        self.env['bxi.face.service']._active_consent(self.student).sudo().write({'withdrawn_at': '2026-01-01'})
        resp = self.url_open(f'/api/v1/admin/face/enrolments/{enrolment.id}/approve', headers=self.manager, json={}, method='POST')
        self.assertEqual(resp.json()['error']['code'], 'consent_required')

    def test_revoke_active(self):
        enrolment = self.enrol(self.teacher_user, 'tara')
        resp = self.url_open(f'/api/v1/admin/face/enrolments/{enrolment.id}/revoke', headers=self.manager,
                             json={'reason': 'left the school'})
        self.assertEqual(resp.json()['data']['state'], 'revoked')
        self.assertEqual(enrolment.end_reason, 'left the school')

    # -- in-person enrolment ----------------------------------------------------------------------

    def test_staff_enrols_teacher_in_person(self):
        resp = self.url_open('/api/v1/admin/face/enrol', headers=self.manager, json={
            'faculty_id': self.faculty.id, 'frames': _frames('tara', (0.0,))})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['state'], 'active')
        self.assertEqual(resp.json()['data']['source'], 'staff')
        self.assertEqual(self.face_login('tara', login_hint='face_teacher').status_code, 200)

    def test_staff_enrolment_of_student_records_offline_consent(self):
        body = {'student_id': self.student.id, 'frames': _frames('sam')}
        resp = self.url_open('/api/v1/admin/face/enrol', headers=self.manager, json=body)
        self.assertEqual(resp.json()['error']['code'], 'consent_required')
        resp = self.url_open('/api/v1/admin/face/enrol', headers=self.manager,
                             json=dict(body, consent_reference='Form 2026/118'))
        self.assertEqual(resp.json()['data']['state'], 'active')
        consent = self.env['bxi.face.service']._active_consent(self.student)
        self.assertEqual(consent.method, 'offline')
        self.assertEqual(consent.reference, 'Form 2026/118')

    def test_staff_enrolment_with_duplicate_stays_pending(self):
        self.enrol(self.parent_user, 'tara')
        resp = self.url_open('/api/v1/admin/face/enrol', headers=self.manager, json={
            'user_id': self.teacher_user.id, 'frames': _frames('tara')})
        self.assertEqual(resp.json()['data']['state'], 'pending')
        self.assertEqual(resp.json()['data']['duplicates'][0]['id'], self.parent_user.id)

    def test_staff_enrol_validation(self):
        resp = self.url_open('/api/v1/admin/face/enrol', headers=self.manager, json={'frames': _frames('x')})
        self.assertEqual(resp.json()['error']['code'], 'missing_fields')
        self.other_student.user_id = False
        resp = self.url_open('/api/v1/admin/face/enrol', headers=self.manager, json={
            'student_id': self.other_student.id, 'frames': _frames('olga')})
        self.assertEqual(resp.json()['error']['code'], 'no_account')

    # -- kiosks --------------------------------------------------------------------------------------

    def _kiosk(self, **extra):
        resp = self.url_open('/api/v1/admin/face/kiosks', headers=self.manager,
                             json=dict({'name': 'Library tablet', 'roles': ['student', 'teacher']}, **extra))
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()['data']

    def test_kiosk_identifies_without_login_hint(self):
        kiosk = self._kiosk(session_minutes=20)
        self.assertTrue(kiosk['key'].startswith('kiosk_'))
        listed = self.url_open('/api/v1/admin/face/kiosks', headers=self.manager).json()['data']
        self.assertNotIn('key', listed[0])

        self.enrol(self.teacher_user, 'tara')
        self.enrol(self.parent_user, 'pat')
        resp = self.face_login('tara', kiosk_key=kiosk['key'])
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertEqual(data['user']['id'], self.teacher_user.id)
        self.assertEqual(data['auth_method'], 'face_kiosk')
        token = self.token_record(data['token'])
        self.assertTrue(token.step_up_required)
        self.assertEqual(token.face_kiosk_id.id, kiosk['id'])

        # Parents aren't allowed on this kiosk; strangers aren't recognised.
        self.assertEqual(self.face_login('pat', kiosk_key=kiosk['key']).status_code, 401)
        self.assertEqual(self.face_login('mallory', kiosk_key=kiosk['key']).status_code, 401)

        # Revoking the kiosk ends its sessions and its key.
        self.url_open(f"/api/v1/admin/face/kiosks/{kiosk['id']}/revoke", headers=self.manager, json={}, method='POST')
        self.assertFalse(token.active)
        self.assertEqual(self.face_login('tara', kiosk_key=kiosk['key']).json()['error']['code'], 'invalid_kiosk')

    def test_kiosk_refuses_lookalikes(self):
        kiosk = self._kiosk()
        self.enrol(self.teacher_user, 'tara')
        twin = self.env['res.users'].create({
            'name': 'Twin', 'login': 'face_twin', 'password': 'TwinPass1!',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('openeducat_core.group_op_faculty').id])],
        })
        analyses = [self.engine.analyze(base64.b64decode(photo('twin', 0.0, like='tara', blend=0.9)))]
        twin_enrolment = self.env['bxi.face.enrolment']._create_from_analyses(twin, analyses, 'staff', self.manager_user)
        twin_enrolment._activate(self.manager_user)
        resp = self.face_login('tara', kiosk_key=kiosk['key'])
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error']['code'], 'ambiguous')

    def test_kiosks_switched_off(self):
        kiosk = self._kiosk()
        self.enrol(self.teacher_user, 'tara')
        self.company.bxi_face_kiosk_enabled = False
        self.assertEqual(self.face_login('tara', kiosk_key=kiosk['key']).json()['error']['code'], 'face_login_disabled')

    def test_kiosk_validation(self):
        resp = self.url_open('/api/v1/admin/face/kiosks', headers=self.manager, json={'name': 'X', 'roles': ['admin']})
        self.assertEqual(resp.json()['error']['code'], 'invalid_roles')
        resp = self.url_open('/api/v1/admin/face/kiosks', headers=self.manager, json={'name': 'X', 'session_minutes': 0})
        self.assertEqual(resp.json()['error']['code'], 'invalid_session_minutes')

    # -- attempts and settings ------------------------------------------------------------------------

    def test_attempt_log(self):
        self.enrol(self.teacher_user, 'tara')
        self.face_login('mallory', login_hint='face_teacher')
        self.face_login('tara', login_hint='face_teacher')
        resp = self.url_open(f'/api/v1/admin/face/attempts?user_id={self.teacher_user.id}', headers=self.manager)
        attempts = resp.json()['data']
        self.assertEqual([a['result'] for a in attempts], ['success', 'face_not_recognised'])
        self.assertEqual(attempts[1]['accounts_tried'][0]['id'], self.teacher_user.id)
        resp = self.url_open('/api/v1/admin/face/attempts?result=success', headers=self.manager)
        self.assertEqual(len(resp.json()['data']), 1)
        resp = self.url_open('/api/v1/admin/face/attempts?result=bogus', headers=self.manager)
        self.assertEqual(resp.status_code, 400)

    def test_settings_read_and_update(self):
        data = self.url_open('/api/v1/admin/face/settings', headers=self.manager).json()['data']
        self.assertTrue(data['enabled'])
        self.assertEqual(data['match_threshold'], 0.45)
        self.assertTrue(data['engine']['available'])
        self.assertIn(data['encryption_key_source'], ('config', 'database'))

        course = self.env['op.course'].create({'name': 'Face Class 9', 'code': 'FC9'})
        resp = self.url_open('/api/v1/admin/face/settings', headers=self.manager, json={
            'kiosk_match_threshold': 0.6, 'max_failures': 3, 'allow_parent': False, 'student_class_ids': [course.id]})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(self.company.bxi_face_kiosk_match_threshold, 0.6)
        self.assertEqual(self.company.bxi_face_max_failures, 3)
        self.assertFalse(self.company.bxi_face_allow_parent)
        self.assertEqual(resp.json()['data']['student_class_ids'][0]['id'], course.id)

        for body in ({'match_threshold': 1.5}, {'max_failures': 2.5}, {'enabled': 'yes'}, {'nope': 1}):
            resp = self.url_open('/api/v1/admin/face/settings', headers=self.manager, json=body)
            self.assertEqual(resp.status_code, 400, body)
