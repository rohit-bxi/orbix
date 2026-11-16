# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64
import io

from PIL import Image

from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from ..lib.engine import FaceError
from .common import FaceHttpCase, FakeEngine, photo

# A record photo is a real image (image_1920 refuses anything else); its
# colour says whose face it shows.
PEOPLE = {(200, 30, 30): 'tara', (30, 200, 30): 'sam', (30, 30, 200): 'pia', (90, 90, 90): None}


def record_photo(person):
    colour = next(colour for colour, who in PEOPLE.items() if who == person)
    buffer = io.BytesIO()
    Image.new('RGB', (64, 64), colour).save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue())


class PhotoEngine(FakeEngine):
    """FakeEngine that also reads the coloured record photos."""

    def analyze(self, image_bytes):
        if image_bytes[:1] == b'{':
            return super().analyze(image_bytes)
        person = PEOPLE.get(Image.open(io.BytesIO(image_bytes)).convert('RGB').getpixel((0, 0)))
        if not person:
            raise FaceError('no_face', 'fake no_face')
        return super().analyze(base64.b64decode(photo(person)))


@tagged('post_install', '-at_install')
class TestRecordPhotoFaceLogin(FaceHttpCase):
    """The photo on the student/teacher/parent record is the face used for
    face login, rebuilt whenever it changes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.engine = PhotoEngine()
        cls.office_user = mail_new_test_user(
            cls.env, login='rp_office', password='OfficePass1!',
            groups='base.group_user,openeducat_core.group_op_back_office_admin')

    def _record_faces(self, user, states=('active', 'pending')):
        return self.env['bxi.face.enrolment'].sudo().search([
            ('user_id', '=', user.id), ('source', '=', 'record'), ('state', 'in', states)])

    def test_teacher_photo_is_the_face(self):
        self.faculty.image_1920 = record_photo('tara')
        face = self._record_faces(self.teacher_user)
        self.assertEqual(face.state, 'active')
        self.assertEqual(self.faculty.face_verification_status, 'verified')
        resp = self.face_login('tara', login_hint='face_teacher')
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['identity']['role'], 'teacher')
        self.assertEqual(self.face_login('sam', login_hint='face_teacher').status_code, 401,
                         'Someone else is not let in.')

    def test_new_photo_replaces_the_face(self):
        self.faculty.image_1920 = record_photo('tara')
        first = self._record_faces(self.teacher_user)
        self.faculty.image_1920 = record_photo('pia')
        self.assertEqual(first.state, 'revoked')
        self.assertFalse(first.template_ids, 'The old face data is deleted.')
        self.assertEqual(self._record_faces(self.teacher_user).state, 'active')
        self.assertEqual(self.face_login('pia', login_hint='face_teacher').status_code, 200)
        self.assertEqual(self.face_login('tara', login_hint='face_teacher').status_code, 401)

    def test_photo_without_a_face(self):
        self.faculty.image_1920 = record_photo('tara')
        self.faculty.image_1920 = record_photo(None)
        self.assertFalse(self._record_faces(self.teacher_user), 'An unusable photo removes the old face.')
        self.assertEqual(self.teacher_user.sudo().bxi_face_photo_error, 'no_face')
        self.faculty.image_1920 = False
        self.assertFalse(self.teacher_user.sudo().bxi_face_photo_error)

    def test_parent_click_image(self):
        self.assertTrue(self.parent.register_face(record_photo('pia').decode()))
        self.assertEqual(self._record_faces(self.parent_user).state, 'active')
        resp = self.face_login('pia', login_hint='face_parent')
        self.assertEqual(resp.json()['data']['identity']['role'], 'parent')

    def test_student_needs_consent_to_sign_in(self):
        self.student.image_1920 = record_photo('sam')
        self.assertEqual(self._record_faces(self.student_user).state, 'active')
        self.assertEqual(self.face_login('sam', login_hint='face_student').status_code, 401,
                         'Consent is still required for students.')
        self.consent()
        self.assertEqual(self.face_login('sam', login_hint='face_student').status_code, 200)

    def test_login_created_after_the_photo(self):
        student = self.env['op.student'].create({
            'first_name': 'Late', 'last_name': 'Login', 'gr_no': 'FACE-LATE', 'gender': 'm',
            'image_1920': record_photo('pia')})
        user = mail_new_test_user(self.env, login='face_late', password='LatePass1!', groups='base.group_portal')
        user.partner_id = student.partner_id
        student.user_id = user
        self.assertEqual(self._record_faces(user).state, 'active')

    def test_same_face_on_another_account_waits_for_review(self):
        self.faculty.image_1920 = record_photo('tara')
        self.parent.image_1920 = record_photo('tara')
        self.assertEqual(self._record_faces(self.parent_user).state, 'pending')
        self.assertEqual(self._record_faces(self.teacher_user).state, 'active')

    def test_setting_and_sync_route(self):
        manager = self.headers('face_manager', 'ManagerPass1!')
        off = self.url_open('/api/v1/admin/face/settings', headers=manager, json={'use_record_photo': False})
        self.assertFalse(off.json()['data']['use_record_photo'])
        self.faculty.image_1920 = record_photo('tara')
        self.assertFalse(self._record_faces(self.teacher_user), 'Switched off: photos are not used.')
        refused = self.url_open('/api/v1/admin/face/sync-record-photos', headers=manager, json={}, method='POST')
        self.assertEqual(refused.json()['error']['code'], 'record_photo_disabled')

        on = self.url_open('/api/v1/admin/face/settings', headers=manager, json={'use_record_photo': True})
        self.assertEqual(on.json()['data']['record_photo_sync'].get('active'), 1, on.text)
        self.assertEqual(self._record_faces(self.teacher_user).state, 'active')
        again = self.url_open('/api/v1/admin/face/sync-record-photos', headers=manager, json={}, method='POST')
        self.assertNotIn('active', again.json()['data']['sync'], 'Unchanged photos are skipped.')
        forced = self.url_open('/api/v1/admin/face/sync-record-photos', headers=manager, json={'force': True})
        self.assertEqual(forced.json()['data']['sync'].get('active'), 1)

        dropped = self.url_open('/api/v1/admin/face/settings', headers=manager, json={'use_record_photo': False})
        self.assertEqual(dropped.json()['data']['record_photo_faces_removed'], 1)
        self.assertFalse(self._record_faces(self.teacher_user))

    def test_face_login_switched_off(self):
        self.company.bxi_face_enabled = False
        self.faculty.image_1920 = record_photo('tara')
        self.assertFalse(self._record_faces(self.teacher_user))
