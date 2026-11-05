# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged

from ..models.face_service import FaceEngineUnavailable
from .common import FaceHttpCase, photo


@tagged('post_install', '-at_install')
class TestFaceLogin(FaceHttpCase):

    # -- challenge ------------------------------------------------------------------

    def test_challenge_starts_straight_then_both_turns(self):
        data = self.challenge()
        self.assertTrue(data['challenge_id'].startswith('fc_'))
        self.assertEqual(data['actions'][0], 'center')
        self.assertEqual(sorted(data['actions'][1:]), ['left', 'right'])
        self.assertEqual(data['expires_in'], 60)

    def test_challenge_is_single_use(self):
        self.enrol(self.teacher_user, 'tara')
        challenge = self.challenge()
        body = {'challenge_id': challenge['challenge_id'], 'login_hint': 'face_teacher',
                'frames': self.frames(challenge['actions'], 'tara')}
        self.assertEqual(self.url_open('/api/v1/auth/face-login', json=body).status_code, 200)
        resp = self.url_open('/api/v1/auth/face-login', json=body)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'challenge_expired')

    def test_expired_challenge_rejected(self):
        challenge = self.challenge()
        self.env['bxi.face.challenge'].sudo().search([('name', '=', challenge['challenge_id'])]).expires_at = \
            fields.Datetime.now() - timedelta(seconds=1)
        resp = self.url_open('/api/v1/auth/face-login', json={
            'challenge_id': challenge['challenge_id'], 'login_hint': 'face_teacher',
            'frames': self.frames(challenge['actions'], 'tara')})
        self.assertEqual(resp.json()['error']['code'], 'challenge_expired')

    def test_frames_must_cover_every_action(self):
        challenge = self.challenge()
        frames = self.frames(challenge['actions'], 'tara')
        frames[2]['action'] = frames[1]['action']
        resp = self.url_open('/api/v1/auth/face-login', json={
            'challenge_id': challenge['challenge_id'], 'login_hint': 'face_teacher', 'frames': frames})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_frames')

    def test_login_hint_required_when_face_only_login_is_off(self):
        self.company.bxi_face_auto_identify = False
        resp = self.face_login('tara')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_login_hint')

    # -- own phone (1:1) ------------------------------------------------------------------

    def test_teacher_logs_in_by_face_with_login_hint(self):
        self.enrol(self.teacher_user, 'tara')
        resp = self.face_login('tara', login_hint='face_teacher', device_name='Tara phone')
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertEqual(data['auth_method'], 'face')
        self.assertEqual(data['user']['id'], self.teacher_user.id)
        self.assertIn('teacher', data['user']['roles'])
        token = self.token_record(data['token'])
        self.assertEqual(token.auth_method, 'face')
        self.assertTrue(token.step_up_required)
        self.assertFalse(token._is_recently_verified())
        attempt = self.env['bxi.face.login.attempt'].sudo().search([], limit=1)
        self.assertEqual(attempt.result, 'success')
        self.assertEqual(attempt.user_id, self.teacher_user)
        self.assertGreater(attempt.best_score, 0.9)

    def test_phone_number_works_as_login_hint(self):
        self.enrol(self.teacher_user, 'tara')
        resp = self.face_login('tara', login_hint='+91 90000-11111')
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['user']['id'], self.teacher_user.id)

    def test_parent_mobile_and_student_registration_number_work_as_hint(self):
        self.enrol(self.parent_user, 'pat')
        self.consent()
        self.enrol(self.student_user, 'sam')
        resp = self.face_login('pat', login_hint='9000022222')
        self.assertEqual(resp.json()['data']['user']['id'], self.parent_user.id)
        resp = self.face_login('sam', login_hint='FACE-001')
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['user']['id'], self.student_user.id)
        self.assertIn('student', resp.json()['data']['user']['roles'])

    def test_someone_else_face_not_recognised(self):
        self.enrol(self.teacher_user, 'tara')
        resp = self.face_login('mallory', login_hint='face_teacher')
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()['error']['code'], 'face_not_recognised')

    def test_unknown_and_unenrolled_accounts_answer_the_same(self):
        unknown = self.face_login('tara', login_hint='nobody-here')
        not_enrolled = self.face_login('tara', login_hint='face_teacher')
        for resp in (unknown, not_enrolled):
            self.assertEqual(resp.status_code, 401)
            self.assertEqual(resp.json()['error']['code'], 'face_not_recognised')

    def test_face_login_off_for_school(self):
        self.enrol(self.teacher_user, 'tara')
        self.company.bxi_face_enabled = False
        resp = self.face_login('tara', login_hint='face_teacher')
        self.assertEqual(resp.json()['error']['code'], 'face_not_recognised')

    def test_role_switched_off(self):
        self.enrol(self.teacher_user, 'tara')
        self.company.bxi_face_allow_teacher = False
        self.assertEqual(self.face_login('tara', login_hint='face_teacher').status_code, 401)

    def test_admin_accounts_excluded_unless_staff_allowed(self):
        admin = self.env.ref('base.user_admin')
        self.enrol(admin, 'ada')
        self.assertEqual(self.face_login('ada', login_hint=admin.login).status_code, 401)
        self.company.bxi_face_allow_staff = True
        self.assertEqual(self.face_login('ada', login_hint=admin.login).status_code, 200)

    def test_student_needs_parent_consent_and_withdrawal_revokes(self):
        consent = self.consent()
        enrolment = self.enrol(self.student_user, 'sam')
        self.assertEqual(self.face_login('sam', login_hint='face_student').status_code, 200)
        consent._withdraw(self.parent_user)
        self.assertEqual(enrolment.state, 'revoked')
        self.assertFalse(enrolment.template_ids)
        self.assertEqual(self.face_login('sam', login_hint='face_student').status_code, 401)

    def test_student_class_filter(self):
        self.consent()
        self.enrol(self.student_user, 'sam')
        course = self.env['op.course'].create({'name': 'Face Class 10', 'code': 'FC10'})
        self.company.bxi_face_student_course_ids = course
        self.assertEqual(self.face_login('sam', login_hint='face_student').status_code, 401)

    # -- liveness ------------------------------------------------------------------------

    def test_flat_photo_without_head_turn_fails_liveness(self):
        self.enrol(self.teacher_user, 'tara')
        resp = self.face_login('tara', login_hint='face_teacher', yaws={'left': 0.02, 'right': -0.01})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()['error']['code'], 'liveness_failed')
        attempt = self.env['bxi.face.login.attempt'].sudo().search([], limit=1)
        self.assertEqual(attempt.reason, 'head_not_turned')

    def test_turns_in_same_direction_fail(self):
        self.enrol(self.teacher_user, 'tara')
        resp = self.face_login('tara', login_hint='face_teacher', yaws={'left': 0.3, 'right': 0.35})
        self.assertEqual(resp.json()['error']['code'], 'liveness_failed')

    def test_mirrored_camera_still_passes(self):
        self.enrol(self.teacher_user, 'tara')
        resp = self.face_login('tara', login_hint='face_teacher', yaws={'left': -0.3, 'right': 0.3})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_photo_for_straight_frame_then_own_head_fails(self):
        self.enrol(self.teacher_user, 'tara')
        challenge = self.challenge()
        frames = self.frames(challenge['actions'], 'mallory')
        for frame in frames:
            if frame['action'] == 'center':
                frame['image'] = photo('tara', 0.0)
        resp = self.url_open('/api/v1/auth/face-login', json={
            'challenge_id': challenge['challenge_id'], 'login_hint': 'face_teacher', 'frames': frames})
        self.assertEqual(resp.json()['error']['code'], 'liveness_failed')
        self.assertEqual(self.env['bxi.face.login.attempt'].sudo().search([], limit=1).reason, 'face_changed')

    def test_passive_antispoof_score_used_when_present(self):
        self.enrol(self.teacher_user, 'tara')
        resp = self.face_login('tara', login_hint='face_teacher', live=0.3)
        self.assertEqual(resp.json()['error']['code'], 'liveness_failed')
        resp = self.face_login('tara', login_hint='face_teacher', live=0.97)
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_liveness_can_be_switched_off(self):
        self.enrol(self.teacher_user, 'tara')
        self.company.bxi_face_liveness_required = False
        resp = self.face_login('tara', login_hint='face_teacher', yaws={'left': 0.0, 'right': 0.0})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_photo_problem_reported_with_action(self):
        challenge = self.challenge()
        frames = self.frames(challenge['actions'], 'tara')
        frames[1]['image'] = photo(error='no_face')
        resp = self.url_open('/api/v1/auth/face-login', json={
            'challenge_id': challenge['challenge_id'], 'login_hint': 'face_teacher', 'frames': frames})
        self.assertEqual(resp.status_code, 400)
        error = resp.json()['error']
        self.assertEqual(error['code'], 'no_face')
        self.assertEqual(error['action'], frames[1]['action'])

    def test_invalid_base64_rejected(self):
        challenge = self.challenge()
        frames = self.frames(challenge['actions'], 'tara')
        frames[0]['image'] = 'not base64 !!!'
        resp = self.url_open('/api/v1/auth/face-login', json={
            'challenge_id': challenge['challenge_id'], 'login_hint': 'face_teacher', 'frames': frames})
        self.assertEqual(resp.json()['error']['code'], 'invalid_image')

    def test_engine_unavailable_answers_503(self):
        self.enrol(self.teacher_user, 'tara')
        with patch.object(type(self.env['bxi.face.service']), '_get_engine', side_effect=FaceEngineUnavailable()):
            resp = self.face_login('tara', login_hint='face_teacher')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()['error']['code'], 'face_engine_unavailable')

    # -- lockout -------------------------------------------------------------------------------

    def test_lockout_after_repeated_failures_and_user_warned(self):
        self.enrol(self.teacher_user, 'tara')
        self.company.bxi_face_max_failures = 3
        for _ in range(3):
            self.assertEqual(self.face_login('mallory', login_hint='face_teacher').status_code, 401)
        resp = self.face_login('tara', login_hint='face_teacher')
        self.assertEqual(resp.status_code, 423)
        self.assertEqual(resp.json()['error']['code'], 'locked')
        warning = self.env['bxi.notification'].sudo().search([
            ('user_id', '=', self.teacher_user.id), ('category', '=', 'security')])
        self.assertEqual(len(warning), 1)
        # Password login is unaffected.
        resp = self.url_open('/api/v1/auth/login', json={'login': 'face_teacher', 'password': 'TeacherPass1!'})
        self.assertEqual(resp.status_code, 200)

    def test_photo_problems_do_not_count_towards_lockout(self):
        self.enrol(self.teacher_user, 'tara')
        self.company.bxi_face_max_failures = 2
        for _ in range(3):
            challenge = self.challenge()
            frames = self.frames(challenge['actions'], 'tara')
            frames[0]['image'] = photo(error='poor_quality')
            self.url_open('/api/v1/auth/face-login', json={
                'challenge_id': challenge['challenge_id'], 'login_hint': 'face_teacher', 'frames': frames})
        self.assertEqual(self.face_login('tara', login_hint='face_teacher').status_code, 200)

    def test_lockout_ends_after_window(self):
        self.enrol(self.teacher_user, 'tara')
        self.company.bxi_face_max_failures = 1
        self.face_login('mallory', login_hint='face_teacher')
        self.assertEqual(self.face_login('tara', login_hint='face_teacher').status_code, 423)
        # create_date can't be written through the ORM.
        self.env.cr.execute("UPDATE bxi_face_login_attempt SET create_date = create_date - interval '1 hour'")
        self.env['bxi.face.login.attempt'].invalidate_model(['create_date'])
        self.assertEqual(self.face_login('tara', login_hint='face_teacher').status_code, 200)

    # -- several accounts, one person ---------------------------------------------------------------

    def test_same_person_with_two_accounts_chooses(self):
        second = self.env['res.users'].create({
            'name': 'Tara as parent', 'login': 'face_teacher_parent', 'password': 'SecondPass1!',
            'phone': '9000011111', 'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        relationship = self.env['op.parent.relationship'].search([], limit=1)
        self.env['op.parent'].create({
            'name': second.partner_id.id, 'relationship_id': relationship.id, 'user_id': second.id,
            'student_ids': [(6, 0, self.other_student.ids)],
        })
        self.enrol(self.teacher_user, 'tara')
        enrolment = self.enrol(second, 'tara')
        enrolment.same_person_user_ids = self.teacher_user

        resp = self.face_login('tara', login_hint='9000011111')
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertTrue(data['selection_required'])
        self.assertEqual({a['user_id'] for a in data['accounts']}, {self.teacher_user.id, second.id})

        bad = self.url_open('/api/v1/auth/face-login/select', json={
            'selection_token': data['selection_token'], 'user_id': self.parent_user.id})
        self.assertEqual(bad.json()['error']['code'], 'invalid_account')
        ok = self.url_open('/api/v1/auth/face-login/select', json={
            'selection_token': data['selection_token'], 'user_id': second.id})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()['data']['user']['id'], second.id)
        self.assertEqual(ok.json()['data']['auth_method'], 'face')
        again = self.url_open('/api/v1/auth/face-login/select', json={
            'selection_token': data['selection_token'], 'user_id': second.id})
        self.assertEqual(again.json()['error']['code'], 'selection_expired')

    def test_two_different_people_on_one_phone_number(self):
        # A shared family number: the face decides, the lookalike gap protects.
        self.teacher_user.phone = '9000033333'
        self.parent_user.phone = '9000033333'
        self.enrol(self.teacher_user, 'tara')
        self.enrol(self.parent_user, 'pat')
        resp = self.face_login('pat', login_hint='9000033333')
        self.assertEqual(resp.json()['data']['user']['id'], self.parent_user.id)

    # -- step-up -----------------------------------------------------------------------------------

    def test_face_session_needs_step_up_for_linking_a_student(self):
        self.enrol(self.parent_user, 'pat')
        token = self.face_login('pat', login_hint='face_parent').json()['data']['token']
        headers = {'Authorization': f'Bearer {token}'}
        self.other_student.birth_date = '2015-02-03'
        body = {'gr_no': 'FACE-002', 'birth_date': '2015-02-03'}
        resp = self.url_open('/api/v1/identity/link-student', headers=headers, json=body)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['error']['code'], 'step_up_required')
        self.url_open('/api/v1/auth/step-up', headers=headers, json={'password': 'ParentPass1!'})
        resp = self.url_open('/api/v1/identity/link-student', headers=headers, json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        # Non-sensitive routes work straight away.
        self.assertEqual(self.url_open('/api/v1/auth/me', headers=headers).status_code, 200)
