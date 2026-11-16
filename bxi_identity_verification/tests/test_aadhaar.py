# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.bxi_identity_verification.models.aadhaar import (
    AadhaarInUseError, aadhaar_hash, is_valid_aadhaar, looks_like_aadhaar, mask_aadhaar, normalize_aadhaar,
    verhoeff_check_digit,
)
from odoo.addons.mail.tests.common import mail_new_test_user


def aadhaar(base11):
    """A valid Aadhaar number: 11 digits + their Verhoeff check digit."""
    return base11 + verhoeff_check_digit(base11)


@tagged('post_install', '-at_install')
class TestAadhaarHelpers(TransactionCase):

    def test_checksum(self):
        self.assertEqual(verhoeff_check_digit('236'), '3', 'Textbook Verhoeff example')
        self.assertTrue(is_valid_aadhaar('234567890124'))
        self.assertFalse(is_valid_aadhaar('234567890125'), 'Wrong check digit')
        self.assertFalse(is_valid_aadhaar('123456789012'), 'Cannot start with 1')
        self.assertFalse(is_valid_aadhaar('0' + aadhaar('1234567890')[1:]), 'Cannot start with 0')
        self.assertFalse(is_valid_aadhaar('23456789012'), '11 digits')
        self.assertFalse(is_valid_aadhaar('23456789012a'))

    def test_normalize_and_detect(self):
        self.assertEqual(normalize_aadhaar('2345 6789 0124'), '234567890124')
        self.assertEqual(normalize_aadhaar('2345-6789-0124'), '234567890124')
        self.assertIsNone(normalize_aadhaar('2345 6789 0125'))
        self.assertIsNone(normalize_aadhaar(None))
        self.assertTrue(looks_like_aadhaar(' 2345 6789 0124 '))
        self.assertFalse(looks_like_aadhaar('admin'))
        self.assertFalse(looks_like_aadhaar('x234567890124'))
        self.assertEqual(mask_aadhaar('0124'), 'XXXX XXXX 0124')

    def test_hash_is_keyed(self):
        digest = aadhaar_hash(self.env, '234567890124')
        self.assertEqual(digest, aadhaar_hash(self.env, '234567890124'))
        self.assertNotEqual(digest, aadhaar_hash(self.env, '345678901238'))
        self.assertNotIn('234567890124', digest)


@tagged('post_install', '-at_install')
class TestAadhaarOnRecords(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.relationship = cls.env['op.parent.relationship'].search([], limit=1) or \
            cls.env['op.parent.relationship'].create({'name': 'Guardian'})
        cls.user_a = mail_new_test_user(cls.env, login='aad_a', groups='base.group_portal')
        cls.user_b = mail_new_test_user(cls.env, login='aad_b', groups='base.group_portal')
        cls.student = cls.env['op.student'].create({
            'first_name': 'Aad', 'last_name': 'Student', 'gr_no': 'AAD-001', 'gender': 'm', 'user_id': cls.user_a.id,
        })
        cls.other_student = cls.env['op.student'].create({
            'first_name': 'Other', 'last_name': 'Student', 'gr_no': 'AAD-002', 'gender': 'f', 'user_id': cls.user_b.id,
        })
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Aad', 'last_name': 'Teacher', 'gender': 'female', 'birth_date': '1985-01-01',
        })

    def test_office_number_is_cleaned_hashed_and_verified(self):
        self.student.write({'aadhar_card': '2345 6789 0124'})
        self.assertEqual(self.student.aadhar_card, '234567890124')
        self.assertEqual(self.student.bxi_aadhaar_last4, '0124')
        self.assertEqual(self.student.bxi_aadhaar_masked, 'XXXX XXXX 0124')
        self.assertEqual(self.student.sudo().bxi_aadhaar_hash, aadhaar_hash(self.env, '234567890124'))
        self.assertEqual(self.student.aadhar_verification_status, 'verified',
                         'A number typed by the school office counts as verified.')
        self.assertTrue(self.student.aadhar_verified_at)

    def test_clearing_resets_status(self):
        self.student.write({'aadhar_card': '234567890124'})
        self.student.write({'aadhar_card': False})
        self.assertFalse(self.student.sudo().bxi_aadhaar_hash)
        self.assertFalse(self.student.bxi_aadhaar_last4)
        self.assertEqual(self.student.aadhar_verification_status, 'unverified')

    def test_family_submission_waits_for_review(self):
        self.student._submit_aadhar('2345 6789 0124')
        self.assertEqual(self.student.aadhar_card, '234567890124')
        self.assertEqual(self.student.aadhar_verification_status, 'pending')
        self.assertFalse(self.student.aadhar_verified_at)
        self.student.action_verify_aadhar()
        self.assertEqual(self.student.aadhar_verification_status, 'verified')

    def test_invalid_number_rejected(self):
        with self.assertRaises(ValidationError):
            self.student.write({'aadhar_card': '234567890125'})
        with self.assertRaises(ValidationError):
            self.student._submit_aadhar('12345')

    def test_same_number_for_another_person_refused(self):
        self.student.write({'aadhar_card': '234567890124'})
        with self.assertRaises(AadhaarInUseError):
            self.other_student.write({'aadhar_card': '234567890124'})
        with self.assertRaises(AadhaarInUseError):
            self.faculty.write({'aadhar_card': '2345-6789-0124'})
        with self.assertRaises(AadhaarInUseError):
            self.other_student._submit_aadhar('234567890124')

    def test_same_person_on_two_records_allowed(self):
        """A parent who is also a teacher, with one login for both."""
        user = mail_new_test_user(self.env, login='aad_both', groups='base.group_user')
        faculty = self.env['op.faculty'].create({
            'first_name': 'Both', 'last_name': 'Roles', 'gender': 'male', 'birth_date': '1980-01-01',
            'user_id': user.id, 'aadhar_card': '345678901238',
        })
        parent = self.env['op.parent'].create({
            'name': user.partner_id.id, 'relationship_id': self.relationship.id, 'user_id': user.id,
            'student_ids': [(6, 0, self.student.ids)], 'aadhar_card': '345678901238',
        })
        self.assertEqual(parent.bxi_aadhaar_last4, faculty.bxi_aadhaar_last4)

    def test_linking_a_login_rechecks_the_number(self):
        """Two records without logins share the contact; linking different
        logins makes them different people."""
        self.faculty.write({'aadhar_card': '456789012341'})
        parent = self.env['op.parent'].create({
            'name': self.faculty.partner_id.id, 'relationship_id': self.relationship.id,
            'student_ids': [(6, 0, self.student.ids)], 'aadhar_card': '456789012341',
        })
        self.faculty.user_id = mail_new_test_user(self.env, login='aad_fac', groups='base.group_user')
        with self.assertRaises(AadhaarInUseError):
            parent.user_id = mail_new_test_user(self.env, login='aad_par', groups='base.group_portal')

    def test_number_is_not_copied(self):
        for model in ('op.student', 'op.faculty', 'op.parent'):
            self.assertFalse(self.env[model]._fields['aadhar_card'].copy, model)


@tagged('post_install', '-at_install')
class TestAadhaarSubmitRoute(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.teacher_user = mail_new_test_user(
            cls.env, login='aad_teacher', groups='base.group_user', password='TeacherPass1!')
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Route', 'last_name': 'Teacher', 'gender': 'female', 'birth_date': '1985-01-01',
            'user_id': cls.teacher_user.id,
        })
        cls.other_faculty = cls.env['op.faculty'].create({
            'first_name': 'Other', 'last_name': 'Teacher', 'gender': 'male', 'birth_date': '1984-01-01',
            'aadhar_card': '876543210988',
        })

    def _headers(self):
        resp = self.url_open('/api/v1/auth/login', json={'login': 'aad_teacher', 'password': 'TeacherPass1!'})
        return {'Authorization': 'Bearer %s' % resp.json()['data']['token']}

    def _submit(self, number, faculty=None):
        return self.url_open('/api/v1/identity/aadhar/submit', headers=self._headers(), json={
            'subject_type': 'teacher', 'subject_id': (faculty or self.faculty).id, 'aadhar_number': number})

    def test_teacher_submits_own_number(self):
        resp = self._submit('9876 5432 1096')
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['aadhar_verification_status'], 'pending')
        self.assertEqual(self.faculty.aadhar_card, '987654321096')

    def test_teacher_cannot_submit_for_another_teacher(self):
        resp = self._submit('987654321096', faculty=self.other_faculty)
        self.assertEqual(resp.status_code, 403)

    def test_invalid_and_taken_numbers(self):
        resp = self._submit('987654321097')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_aadhar')
        resp = self._submit('876543210988')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error']['code'], 'aadhaar_in_use')
        self.assertNotIn('Other', resp.text, 'The holder is not revealed.')
