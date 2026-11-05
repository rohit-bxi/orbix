# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64

from odoo.tests import tagged

from .common import FaceHttpCase, photo


@tagged('post_install', '-at_install')
class TestFaceIdentity(FaceHttpCase):
    """The face alone tells who someone is and whether they are a
    student, teacher or parent: face-only login and /face/identify."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({'name': 'Class 7', 'code': 'FID-7'})
        cls.batch = cls.env['op.batch'].create({
            'name': '7-B', 'code': 'FID-7B', 'course_id': cls.course.id,
            'start_date': '2026-01-01', 'end_date': '2027-12-31',
        })
        cls.env['op.student.course'].create({
            'student_id': cls.student.id, 'course_id': cls.course.id, 'batch_id': cls.batch.id, 'state': 'running',
        })

    def _identify(self, person, headers=None, **extra):
        challenge = self.challenge()
        return self.url_open('/api/v1/face/identify', headers=headers, json={
            'challenge_id': challenge['challenge_id'],
            'frames': self.frames(challenge['actions'], person, **extra)})

    def _lookalike(self, like, login='face_twin'):
        twin = self.env['res.users'].create({
            'name': 'Twin', 'login': login, 'password': 'TwinPass1!',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('openeducat_core.group_op_faculty').id])],
        })
        analyses = [self.engine.analyze(base64.b64decode(photo('twin', 0.0, like=like, blend=0.9)))]
        self.env['bxi.face.enrolment']._create_from_analyses(
            twin, analyses, 'staff', self.manager_user)._activate(self.manager_user)
        return twin

    # -- face-only login ---------------------------------------------------------------

    def test_face_alone_logs_in_a_teacher(self):
        self.enrol(self.teacher_user, 'tara')
        self.enrol(self.parent_user, 'pat')
        resp = self.face_login('tara')
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertEqual(data['user']['id'], self.teacher_user.id)
        self.assertEqual(data['auth_method'], 'face')
        self.assertEqual(data['identity']['role'], 'teacher')
        self.assertEqual(data['identity']['roles'], ['teacher'])
        self.assertEqual(data['identity']['teacher']['id'], self.faculty.id)
        self.assertIsNone(data['identity']['student'])
        self.assertIsNone(data['identity']['parent'])
        self.assertTrue(self.token_record(data['token']).step_up_required)
        self.assertEqual(self.env['bxi.face.login.attempt'].sudo().search([], limit=1).mode, 'auto')

    def test_face_alone_logs_in_a_student_with_class(self):
        self.consent()
        self.enrol(self.student_user, 'sam')
        data = self.face_login('sam').json()['data']
        identity = data['identity']
        self.assertEqual(identity['role'], 'student')
        self.assertEqual(identity['student']['id'], self.student.id)
        self.assertEqual(identity['student']['gr_no'], 'FACE-001')
        self.assertEqual(identity['student']['class']['name'], 'Class 7')
        self.assertEqual(identity['student']['section']['name'], '7-B')

    def test_face_alone_logs_in_a_parent_with_children(self):
        self.enrol(self.parent_user, 'pat')
        identity = self.face_login('pat').json()['data']['identity']
        self.assertEqual(identity['role'], 'parent')
        self.assertEqual(identity['parent']['id'], self.parent.id)
        self.assertEqual([child['id'] for child in identity['parent']['children']], [self.student.id])
        self.assertEqual(identity['parent']['children'][0]['class']['name'], 'Class 7')

    def test_teacher_who_is_also_a_parent(self):
        relationship = self.env['op.parent.relationship'].search([], limit=1)
        self.env['op.parent'].create({
            'name': self.teacher_user.partner_id.id, 'relationship_id': relationship.id,
            'user_id': self.teacher_user.id, 'student_ids': [(6, 0, self.other_student.ids)],
        })
        self.enrol(self.teacher_user, 'tara')
        identity = self.face_login('tara').json()['data']['identity']
        self.assertEqual(identity['role'], 'teacher')
        self.assertEqual(identity['roles'], ['teacher', 'parent'])
        self.assertEqual(identity['parent']['children'][0]['id'], self.other_student.id)
        # Roles switched off for face login are not offered.
        self.company.bxi_face_allow_teacher = False
        identity = self.face_login('tara').json()['data']['identity']
        self.assertEqual(identity['role'], 'parent')
        self.assertIsNone(identity['teacher'])

    def test_face_alone_uses_the_strict_school_wide_rules(self):
        self.enrol(self.teacher_user, 'tara')
        self._lookalike('tara')
        resp = self.face_login('tara')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error']['code'], 'ambiguous')
        # With a login hint only that account is compared, so it works.
        self.assertEqual(self.face_login('tara', login_hint='face_teacher').status_code, 200)

    def test_face_alone_threshold_is_the_kiosk_one(self):
        self.enrol(self.teacher_user, 'tara')
        self.company.bxi_face_kiosk_match_threshold = 0.9999
        # A slightly different straight photo (the fake engine gives an exact
        # 1.0 for a pixel-identical one): ~0.99, below 0.9999, above 0.45.
        yaws = {'center': 0.01}
        self.assertEqual(self.face_login('tara', yaws=yaws).json()['error']['code'], 'face_not_recognised')
        self.assertEqual(self.face_login('tara', login_hint='face_teacher', yaws=yaws).status_code, 200)

    def test_stranger_not_recognised(self):
        self.enrol(self.teacher_user, 'tara')
        resp = self.face_login('mallory')
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()['error']['code'], 'face_not_recognised')

    def test_face_alone_still_checks_liveness(self):
        self.enrol(self.teacher_user, 'tara')
        resp = self.face_login('tara', yaws={'left': 0.0, 'right': 0.01})
        self.assertEqual(resp.json()['error']['code'], 'liveness_failed')

    def test_login_with_hint_also_returns_identity(self):
        self.enrol(self.parent_user, 'pat')
        identity = self.face_login('pat', login_hint='face_parent').json()['data']['identity']
        self.assertEqual(identity['role'], 'parent')

    def test_account_choice_shows_each_role(self):
        second = self.env['res.users'].create({
            'name': 'Tara as parent', 'login': 'face_teacher_parent', 'password': 'SecondPass1!',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        relationship = self.env['op.parent.relationship'].search([], limit=1)
        self.env['op.parent'].create({
            'name': second.partner_id.id, 'relationship_id': relationship.id, 'user_id': second.id,
            'student_ids': [(6, 0, self.other_student.ids)],
        })
        self.enrol(self.teacher_user, 'tara')
        self.enrol(second, 'tara').same_person_user_ids = self.teacher_user
        data = self.face_login('tara').json()['data']
        self.assertTrue(data['selection_required'])
        self.assertEqual({account['user_id']: account['role'] for account in data['accounts']},
                         {self.teacher_user.id: 'teacher', second.id: 'parent'})
        chosen = self.url_open('/api/v1/auth/face-login/select', json={
            'selection_token': data['selection_token'], 'user_id': second.id}).json()['data']
        self.assertEqual(chosen['identity']['role'], 'parent')

    def test_kiosk_login_identity_respects_kiosk_roles(self):
        relationship = self.env['op.parent.relationship'].search([], limit=1)
        self.env['op.parent'].create({
            'name': self.teacher_user.partner_id.id, 'relationship_id': relationship.id,
            'user_id': self.teacher_user.id, 'student_ids': [(6, 0, self.other_student.ids)],
        })
        self.enrol(self.teacher_user, 'tara')
        kiosk, key = self.env['bxi.face.kiosk']._create_with_key({
            'name': 'Staff room', 'allow_student': False, 'allow_teacher': True, 'allow_parent': False})
        identity = self.face_login('tara', kiosk_key=key).json()['data']['identity']
        self.assertEqual(identity['roles'], ['teacher'])

    # -- identify without logging in ----------------------------------------------------------

    def test_manager_identifies_without_creating_a_session(self):
        self.consent()
        self.enrol(self.student_user, 'sam')
        manager = self.headers('face_manager', 'ManagerPass1!')
        Token = self.env['bxi.api.token'].sudo()
        before = Token.search_count([('user_id', '=', self.student_user.id)])
        resp = self._identify('sam', headers=manager)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertTrue(data['identified'])
        self.assertEqual(data['identity']['role'], 'student')
        self.assertEqual(data['identity']['student']['class']['name'], 'Class 7')
        self.assertNotIn('token', data)
        self.assertEqual(Token.search_count([('user_id', '=', self.student_user.id)]), before)
        attempt = self.env['bxi.face.login.attempt'].sudo().search([], limit=1)
        self.assertEqual((attempt.mode, attempt.result, attempt.user_id), ('identify', 'identified', self.student_user))

    def test_identify_unknown_and_ambiguous_faces(self):
        self.enrol(self.teacher_user, 'tara')
        manager = self.headers('face_manager', 'ManagerPass1!')
        data = self._identify('mallory', headers=manager).json()['data']
        self.assertEqual((data['identified'], data['reason'], data['identity']), (False, 'face_not_recognised', None))
        self._lookalike('tara')
        data = self._identify('tara', headers=manager).json()['data']
        self.assertEqual((data['identified'], data['reason']), (False, 'ambiguous'))

    def test_identify_from_kiosk(self):
        self.enrol(self.teacher_user, 'tara')
        self.enrol(self.parent_user, 'pat')
        kiosk, key = self.env['bxi.face.kiosk']._create_with_key({
            'name': 'Gate', 'allow_teacher': True, 'allow_parent': False})
        data = self._identify('tara', headers={'X-Kiosk-Key': key}).json()['data']
        self.assertEqual(data['identity']['role'], 'teacher')
        # Parents aren't allowed on this kiosk.
        self.assertFalse(self._identify('pat', headers={'X-Kiosk-Key': key}).json()['data']['identified'])

    def test_identify_is_not_open_to_everyone(self):
        self.enrol(self.teacher_user, 'tara')
        resp = self._identify('tara')
        self.assertEqual(resp.status_code, 401)
        resp = self._identify('tara', headers=self.headers('face_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 403)
        resp = self._identify('tara', headers={'X-Kiosk-Key': 'kiosk_nope'})
        self.assertEqual(resp.json()['error']['code'], 'invalid_kiosk')

    def test_identify_still_checks_photos_and_liveness(self):
        self.enrol(self.teacher_user, 'tara')
        manager = self.headers('face_manager', 'ManagerPass1!')
        resp = self._identify('tara', headers=manager, yaws={'left': 0.0, 'right': 0.0})
        self.assertEqual(resp.json()['error']['code'], 'liveness_failed')
        challenge = self.challenge()
        frames = self.frames(challenge['actions'], 'tara')
        frames[0]['image'] = photo(error='no_face')
        resp = self.url_open('/api/v1/face/identify', headers=manager,
                             json={'challenge_id': challenge['challenge_id'], 'frames': frames})
        self.assertEqual(resp.json()['error']['code'], 'no_face')

    def test_settings_switch(self):
        manager = self.headers('face_manager', 'ManagerPass1!')
        data = self.url_open('/api/v1/admin/face/settings', headers=manager).json()['data']
        self.assertTrue(data['auto_identify_enabled'])
        self.url_open('/api/v1/admin/face/settings', headers=manager, json={'auto_identify_enabled': False})
        self.assertFalse(self.company.bxi_face_auto_identify)
