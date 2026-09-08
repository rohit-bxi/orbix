# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64
from io import BytesIO

from PIL import Image as PILImage

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


def _tiny_png_base64():
    buf = BytesIO()
    PILImage.new('RGB', (2, 2), color=(10, 20, 30)).save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()


@tagged('post_install', '-at_install')
class TestBxiIdentityVerificationMixinModel(TransactionCase):
    """Model-level, one-method-per-test coverage for
    bxi.identity.verification.mixin methods, called directly on the
    record (record.method(...)) rather than via HTTP routes. The HTTP
    surface is already covered separately in tests/test_identity.py.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student = cls.env['op.student'].create({
            'first_name': 'Mixin', 'last_name': 'Student', 'gr_no': 'MX-001', 'gender': 'f',
        })
        relationship = cls.env['op.parent.relationship'].search([], limit=1) or cls.env['op.parent.relationship'].create({
            'name': 'Guardian',
        })
        cls.parent = cls.env['op.parent'].create({
            'name': cls.env['res.partner'].create({'name': 'Mixin Parent', 'is_parent': True}).id,
            'relationship_id': relationship.id,
            'student_ids': [(6, 0, [cls.student.id])],
        })

    # -- _submit_aadhar --------------------------------------------------------

    def test_submit_aadhar_success_on_student(self):
        self.student._submit_aadhar('123456789012')
        self.assertEqual(self.student.aadhar_card, '123456789012')
        self.assertEqual(self.student.aadhar_verification_status, 'pending')
        self.assertTrue(self.student.aadhar_submitted_at)

    def test_submit_aadhar_success_on_parent(self):
        self.parent._submit_aadhar('999988887777')
        self.assertEqual(self.parent.aadhar_card, '999988887777')
        self.assertEqual(self.parent.aadhar_verification_status, 'pending')
        self.assertTrue(self.parent.aadhar_submitted_at)

    def test_submit_aadhar_without_number_raises_user_error(self):
        with self.assertRaises(UserError):
            self.student._submit_aadhar('')

    # -- _submit_face ------------------------------------------------------------

    def test_submit_face_success_on_student(self):
        self.student._submit_face(_tiny_png_base64())
        self.assertEqual(self.student.face_verification_status, 'pending')
        self.assertTrue(self.student.face_submitted_at)
        self.assertTrue(self.student.image_1920)

    def test_submit_face_success_on_parent(self):
        self.parent._submit_face(_tiny_png_base64())
        self.assertEqual(self.parent.face_verification_status, 'pending')
        self.assertTrue(self.parent.face_submitted_at)
        self.assertTrue(self.parent.image_1920)

    def test_submit_face_without_image_raises_user_error(self):
        with self.assertRaises(UserError):
            self.student._submit_face('')

    # -- action_verify_aadhar -------------------------------------------------

    def test_action_verify_aadhar_sets_verified_and_timestamp(self):
        self.student._submit_aadhar('123456789012')
        self.student.action_verify_aadhar()
        self.assertEqual(self.student.aadhar_verification_status, 'verified')
        self.assertTrue(self.student.aadhar_verified_at)

    # -- action_reject_aadhar --------------------------------------------------

    def test_action_reject_aadhar_sets_rejected(self):
        self.student._submit_aadhar('123456789012')
        self.student.action_reject_aadhar()
        self.assertEqual(self.student.aadhar_verification_status, 'rejected')

    # -- action_verify_face -----------------------------------------------------

    def test_action_verify_face_sets_verified_and_timestamp(self):
        self.student._submit_face(_tiny_png_base64())
        self.student.action_verify_face()
        self.assertEqual(self.student.face_verification_status, 'verified')
        self.assertTrue(self.student.face_verified_at)

    # -- action_reject_face ------------------------------------------------------

    def test_action_reject_face_sets_rejected(self):
        self.student._submit_face(_tiny_png_base64())
        self.student.action_reject_face()
        self.assertEqual(self.student.face_verification_status, 'rejected')
