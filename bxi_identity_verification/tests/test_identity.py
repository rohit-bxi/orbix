import base64
from io import BytesIO

from PIL import Image as PILImage

from odoo.tests import HttpCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


def _tiny_png_base64():
    buf = BytesIO()
    PILImage.new('RGB', (2, 2), color=(10, 20, 30)).save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()


@tagged('post_install', '-at_install')
class TestBxiIdentityVerification(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student = cls.env['op.student'].create({
            'first_name': 'Identity', 'last_name': 'Checked', 'gr_no': 'ID-001', 'gender': 'f',
        })
        cls.parent_user = mail_new_test_user(
            cls.env, login='id_parent', groups='base.group_portal', password='ParentPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='id_other', groups='base.group_portal', password='OtherPass1!')
        cls.staff_user = mail_new_test_user(
            cls.env, login='id_staff', groups='base.group_user,bxi_identity_verification.group_identity_reviewer',
            password='StaffPass1!')

        relationship = cls.env['op.parent.relationship'].search([], limit=1) or cls.env['op.parent.relationship'].create({
            'name': 'Guardian',
        })
        cls.parent = cls.env['op.parent'].create({
            'name': cls.env['res.partner'].create({'name': 'Identity Parent', 'is_parent': True}).id,
            'relationship_id': relationship.id,
            'user_id': cls.parent_user.id,
            'student_ids': [(6, 0, [cls.student.id])],
        })

    def _token(self, login, password):
        resp = self.url_open('/api/v1/auth/login', json={'login': login, 'password': password})
        return resp.json()['data']['token']

    def _headers(self, login, password):
        return {'Authorization': f'Bearer {self._token(login, password)}'}

    # -- aadhaar submit ----------------------------------------------------------

    def test_submit_aadhar_by_linked_parent_succeeds(self):
        resp = self.url_open('/api/v1/identity/aadhar/submit', headers=self._headers('id_parent', 'ParentPass1!'), json={
            'subject_type': 'student', 'subject_id': self.student.id, 'aadhar_number': '123456789012',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['aadhar_verification_status'], 'pending')
        self.assertEqual(self.student.aadhar_card, '123456789012')

    def test_submit_aadhar_by_unrelated_user_forbidden(self):
        resp = self.url_open('/api/v1/identity/aadhar/submit', headers=self._headers('id_other', 'OtherPass1!'), json={
            'subject_type': 'student', 'subject_id': self.student.id, 'aadhar_number': '123456789012',
        })
        self.assertEqual(resp.status_code, 403)

    def test_submit_aadhar_missing_fields_rejected(self):
        resp = self.url_open('/api/v1/identity/aadhar/submit', headers=self._headers('id_parent', 'ParentPass1!'), json={
            'subject_type': 'student', 'subject_id': self.student.id,
        })
        self.assertEqual(resp.status_code, 400)

    def test_submit_aadhar_invalid_subject_type_rejected(self):
        resp = self.url_open('/api/v1/identity/aadhar/submit', headers=self._headers('id_parent', 'ParentPass1!'), json={
            'subject_type': 'teacher', 'subject_id': self.student.id, 'aadhar_number': '123456789012',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_subject_type')

    def test_submit_aadhar_not_found(self):
        resp = self.url_open('/api/v1/identity/aadhar/submit', headers=self._headers('id_parent', 'ParentPass1!'), json={
            'subject_type': 'student', 'subject_id': 999999, 'aadhar_number': '123456789012',
        })
        self.assertEqual(resp.status_code, 404)

    def test_submit_aadhar_for_own_parent_record(self):
        resp = self.url_open('/api/v1/identity/aadhar/submit', headers=self._headers('id_parent', 'ParentPass1!'), json={
            'subject_type': 'parent', 'subject_id': self.parent.id, 'aadhar_number': '999988887777',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.parent.aadhar_card, '999988887777')

    def test_staff_can_submit_for_any_student(self):
        resp = self.url_open('/api/v1/identity/aadhar/submit', headers=self._headers('id_staff', 'StaffPass1!'), json={
            'subject_type': 'student', 'subject_id': self.student.id, 'aadhar_number': '111122223333',
        })
        self.assertEqual(resp.status_code, 200)

    # -- face submit ---------------------------------------------------------------

    def test_submit_face_stores_image_and_sets_pending(self):
        image = _tiny_png_base64()
        resp = self.url_open('/api/v1/identity/face/submit', headers=self._headers('id_parent', 'ParentPass1!'), json={
            'subject_type': 'student', 'subject_id': self.student.id, 'image': image,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['face_verification_status'], 'pending')
        self.assertTrue(self.student.image_1920)

    def test_submit_face_unrelated_user_forbidden(self):
        resp = self.url_open('/api/v1/identity/face/submit', headers=self._headers('id_other', 'OtherPass1!'), json={
            'subject_type': 'student', 'subject_id': self.student.id, 'image': _tiny_png_base64(),
        })
        self.assertEqual(resp.status_code, 403)

    def test_submit_face_missing_fields_rejected(self):
        resp = self.url_open('/api/v1/identity/face/submit', headers=self._headers('id_parent', 'ParentPass1!'), json={
            'subject_type': 'student', 'subject_id': self.student.id,
        })
        self.assertEqual(resp.status_code, 400)

    def test_submit_face_for_own_parent_record(self):
        resp = self.url_open('/api/v1/identity/face/submit', headers=self._headers('id_parent', 'ParentPass1!'), json={
            'subject_type': 'parent', 'subject_id': self.parent.id, 'image': _tiny_png_base64(),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['face_verification_status'], 'pending')
        self.assertTrue(self.parent.image_1920)

    # -- status ---------------------------------------------------------------------

    def test_status_reports_both_fields(self):
        self.student.write({'aadhar_verification_status': 'verified', 'face_verification_status': 'pending'})
        resp = self.url_open(
            f'/api/v1/identity/status?subject_type=student&subject_id={self.student.id}',
            headers=self._headers('id_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']
        self.assertEqual(data['aadhar_verification_status'], 'verified')
        self.assertEqual(data['face_verification_status'], 'pending')

    def test_status_missing_fields_rejected(self):
        resp = self.url_open(
            '/api/v1/identity/status', headers=self._headers('id_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_fields')

    def test_status_invalid_subject_type_rejected(self):
        resp = self.url_open(
            f'/api/v1/identity/status?subject_type=teacher&subject_id={self.student.id}',
            headers=self._headers('id_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_subject_type')

    def test_status_not_found(self):
        resp = self.url_open(
            '/api/v1/identity/status?subject_type=student&subject_id=999999',
            headers=self._headers('id_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 404)

    def test_status_unrelated_user_forbidden(self):
        resp = self.url_open(
            f'/api/v1/identity/status?subject_type=student&subject_id={self.student.id}',
            headers=self._headers('id_other', 'OtherPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_status_requires_auth_token(self):
        resp = self.url_open(
            f'/api/v1/identity/status?subject_type=student&subject_id={self.student.id}')
        self.assertEqual(resp.status_code, 401)

    # -- staff review actions (backend, called directly) -----------------------------

    def test_action_verify_aadhar_sets_verified_and_timestamp(self):
        self.student.sudo()._submit_aadhar('123456789012')
        self.student.action_verify_aadhar()
        self.assertEqual(self.student.aadhar_verification_status, 'verified')
        self.assertTrue(self.student.aadhar_verified_at)

    def test_action_reject_aadhar_sets_rejected(self):
        self.student.sudo()._submit_aadhar('123456789012')
        self.student.action_reject_aadhar()
        self.assertEqual(self.student.aadhar_verification_status, 'rejected')

    def test_action_verify_face_sets_verified_and_timestamp(self):
        self.student.sudo()._submit_face(_tiny_png_base64())
        self.student.action_verify_face()
        self.assertEqual(self.student.face_verification_status, 'verified')
        self.assertTrue(self.student.face_verified_at)

    def test_action_reject_face_sets_rejected(self):
        self.student.sudo()._submit_face(_tiny_png_base64())
        self.student.action_reject_face()
        self.assertEqual(self.student.face_verification_status, 'rejected')

    # -- link/unlink student -----------------------------------------------------------

    def test_link_student_adds_to_parent(self):
        new_student = self.env['op.student'].create({
            'first_name': 'Sibling', 'last_name': 'Checked', 'gr_no': 'ID-002', 'gender': 'm',
        })
        resp = self.url_open('/api/v1/identity/link-student', headers=self._headers('id_parent', 'ParentPass1!'), json={
            'student_id': new_student.id,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(new_student.id, resp.json()['data']['linked_student_ids'])
        self.assertIn(new_student.id, self.parent.student_ids.ids)

    def test_unlink_student_removes_from_parent(self):
        resp = self.url_open('/api/v1/identity/unlink-student', headers=self._headers('id_parent', 'ParentPass1!'), json={
            'student_id': self.student.id,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.student.id, self.parent.student_ids.ids)

    def test_link_student_requires_own_parent_record(self):
        resp = self.url_open('/api/v1/identity/link-student', headers=self._headers('id_other', 'OtherPass1!'), json={
            'student_id': self.student.id,
        })
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['error']['code'], 'not_a_parent')

    def test_link_student_missing_fields_rejected(self):
        resp = self.url_open(
            '/api/v1/identity/link-student', headers=self._headers('id_parent', 'ParentPass1!'), json={}, method='POST')
        self.assertEqual(resp.status_code, 400)

    def test_link_student_not_found(self):
        resp = self.url_open('/api/v1/identity/link-student', headers=self._headers('id_parent', 'ParentPass1!'), json={
            'student_id': 999999,
        })
        self.assertEqual(resp.status_code, 404)

    def test_unlink_student_missing_fields_rejected(self):
        resp = self.url_open(
            '/api/v1/identity/unlink-student', headers=self._headers('id_parent', 'ParentPass1!'), json={}, method='POST')
        self.assertEqual(resp.status_code, 400)

    def test_unlink_student_requires_own_parent_record(self):
        resp = self.url_open('/api/v1/identity/unlink-student', headers=self._headers('id_other', 'OtherPass1!'), json={
            'student_id': self.student.id,
        })
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['error']['code'], 'not_a_parent')
