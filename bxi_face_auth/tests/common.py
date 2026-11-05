# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64
import hashlib
import json
from unittest.mock import patch

import numpy as np

from odoo.tests import HttpCase

from odoo.addons.mail.tests.common import mail_new_test_user

from ..lib.engine import FaceAnalysis, FaceError, normalize


def _vector(seed_text):
    seed = int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], 'little')
    return np.random.default_rng(seed).standard_normal(128)


class FakeEngine:
    """Deterministic stand-in for the OpenCV engine. A test "photo" is
    JSON: {"person": "alice", "yaw": 0.0, "live": 0.99}, or
    {"error": "no_face"}. The same person always gives nearly the same
    embedding; {"like": "alice", "blend": 0.8} makes a lookalike."""
    model_version = 'fake-1'
    has_antispoof = False

    def analyze(self, image_bytes):
        try:
            spec = json.loads(image_bytes)
        except ValueError:
            raise FaceError('invalid_image', 'not a test photo')
        if spec.get('error'):
            raise FaceError(spec['error'], 'fake %s' % spec['error'])
        base = _vector(spec['person'])
        if spec.get('like'):
            blend = spec.get('blend', 0.8)
            base = blend * normalize(_vector(spec['like'])) * 11.3 + (1 - blend) * base
        noise = _vector('%s/%s' % (spec['person'], spec.get('yaw', 0.0))) * 0.08
        return FaceAnalysis(
            embedding=normalize(base + noise),
            yaw=spec.get('yaw', 0.0),
            det_score=0.95,
            face_pixels=160,
            sharpness=500.0,
            live_score=spec.get('live'),
            jpeg=b'\xff\xd8 fake jpeg of ' + spec['person'].encode(),
        )


def photo(person=None, yaw=0.0, **extra):
    spec = dict(extra, yaw=yaw)
    if person:
        spec['person'] = person
    return base64.b64encode(json.dumps(spec).encode()).decode()


YAWS = {'center': 0.0, 'left': 0.3, 'right': -0.3}


class FaceHttpCase(HttpCase):
    """A school with face login on: a teacher, a parent with a child who
    has an app account, a face-login manager and an unrelated parent."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({'bxi_face_enabled': True})
        cls.engine = FakeEngine()

        cls.teacher_user = mail_new_test_user(
            cls.env, login='face_teacher', password='TeacherPass1!', phone='9000011111',
            groups='base.group_user,openeducat_core.group_op_faculty')
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Tara', 'last_name': 'Teacher', 'gender': 'female',
            'birth_date': '1985-01-01', 'user_id': cls.teacher_user.id,
        })
        cls.student_user = mail_new_test_user(
            cls.env, login='face_student', password='StudentPass1!', groups='base.group_portal')
        cls.student = cls.env['op.student'].create({
            'first_name': 'Sam', 'last_name': 'Student', 'gr_no': 'FACE-001', 'gender': 'm',
            'birth_date': '2014-05-06', 'user_id': cls.student_user.id,
        })
        cls.parent_user = mail_new_test_user(
            cls.env, login='face_parent', password='ParentPass1!', groups='base.group_portal')
        relationship = cls.env['op.parent.relationship'].search([], limit=1) or \
            cls.env['op.parent.relationship'].create({'name': 'Guardian'})
        cls.parent = cls.env['op.parent'].create({
            'name': cls.parent_user.partner_id.id, 'relationship_id': relationship.id,
            'user_id': cls.parent_user.id, 'mobile': '9000022222', 'student_ids': [(6, 0, cls.student.ids)],
        })
        cls.other_parent_user = mail_new_test_user(
            cls.env, login='face_other_parent', password='OtherPass1!', groups='base.group_portal')
        cls.other_student = cls.env['op.student'].create({
            'first_name': 'Olga', 'last_name': 'Other', 'gr_no': 'FACE-002', 'gender': 'f',
        })
        cls.env['op.parent'].create({
            'name': cls.other_parent_user.partner_id.id, 'relationship_id': relationship.id,
            'user_id': cls.other_parent_user.id, 'student_ids': [(6, 0, cls.other_student.ids)],
        })
        cls.manager_user = mail_new_test_user(
            cls.env, login='face_manager', password='ManagerPass1!',
            groups='base.group_user,bxi_face_auth.group_face_manager')

    def setUp(self):
        super().setUp()
        patcher = patch.object(type(self.env['bxi.face.service']), '_get_engine', return_value=self.engine)
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- helpers -----------------------------------------------------------------

    def headers(self, login, password):
        resp = self.url_open('/api/v1/auth/login', json={'login': login, 'password': password})
        return {'Authorization': f'Bearer {resp.json()["data"]["token"]}'}

    def enrol(self, user, person):
        """An active enrolment for `user`, as staff would create it."""
        analyses = [self.engine.analyze(base64.b64decode(photo(person, yaw))) for yaw in (0.0, 0.25, -0.25)]
        enrolment = self.env['bxi.face.enrolment']._create_from_analyses(
            user, analyses, 'staff', self.manager_user, consent_by=user)
        enrolment._activate(self.manager_user)
        return enrolment

    def consent(self, student=None):
        return self.env['bxi.face.consent']._grant(student or self.student, self.parent_user)

    def challenge(self):
        return self.url_open('/api/v1/auth/face-login/challenge', json={}, method='POST').json()['data']

    def frames(self, actions, person, yaws=None, **extra):
        yaws = dict(YAWS, **(yaws or {}))
        return [{'action': action, 'image': photo(person, yaws[action], **extra)} for action in actions]

    def face_login(self, person, login_hint=None, kiosk_key=None, yaws=None, frames=None, **extra):
        challenge = self.challenge()
        body = {
            'challenge_id': challenge['challenge_id'],
            'frames': frames or self.frames(challenge['actions'], person, yaws, **extra),
        }
        if login_hint:
            body['login_hint'] = login_hint
        headers = {'X-Kiosk-Key': kiosk_key} if kiosk_key else None
        return self.url_open('/api/v1/auth/face-login', json=body, headers=headers)

    def token_record(self, raw):
        Token = self.env['bxi.api.token']
        return Token.sudo().search([('token_hash', '=', Token._hash(raw))])
