# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged('post_install', '-at_install')
class TestAadhaarVerificationProcess(HttpCase):
    """Submit -> pending list -> verify / reject, for students, parents and
    teachers, plus the status reply."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student_user = mail_new_test_user(cls.env, login='rv_student', password='StudentPass1!',
                                              groups='base.group_portal')
        cls.student = cls.env['op.student'].create({
            'first_name': 'Rev', 'last_name': 'Student', 'gr_no': 'RV-001', 'gender': 'm',
            'user_id': cls.student_user.id,
        })
        cls.parent_user = mail_new_test_user(cls.env, login='rv_parent', password='ParentPass1!',
                                             groups='base.group_portal')
        relationship = cls.env['op.parent.relationship'].search([], limit=1) or \
            cls.env['op.parent.relationship'].create({'name': 'Guardian'})
        cls.parent = cls.env['op.parent'].create({
            'name': cls.parent_user.partner_id.id, 'relationship_id': relationship.id,
            'user_id': cls.parent_user.id, 'student_ids': [(6, 0, cls.student.ids)],
        })
        cls.teacher_user = mail_new_test_user(cls.env, login='rv_teacher', password='TeacherPass1!',
                                              groups='base.group_user')
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Rev', 'last_name': 'Teacher', 'gender': 'female', 'birth_date': '1985-01-01',
            'user_id': cls.teacher_user.id,
        })
        mail_new_test_user(cls.env, login='rv_reviewer', password='ReviewPass1!',
                           groups='base.group_user,bxi_identity_verification.group_identity_reviewer')
        mail_new_test_user(cls.env, login='rv_office', password='OfficePass1!',
                           groups='base.group_user,openeducat_core.group_op_back_office_admin')

    def _headers(self, login, password):
        resp = self.url_open('/api/v1/auth/login', json={'login': login, 'password': password})
        return {'Authorization': 'Bearer %s' % resp.json()['data']['token']}

    def _submit(self, headers, subject_type, subject, number):
        return self.url_open('/api/v1/identity/aadhar/submit', headers=headers, json={
            'subject_type': subject_type, 'subject_id': subject.id, 'aadhar_number': number})

    def _review(self, headers, subject_type, subject, decision, **extra):
        body = {'subject_type': subject_type, 'subject_id': subject.id, 'decision': decision}
        body.update(extra)
        return self.url_open('/api/v1/identity/aadhar/review', headers=headers, json=body)

    def test_full_process_for_each_role(self):
        reviewer = self._headers('rv_reviewer', 'ReviewPass1!')
        for login, password, subject_type, subject, number in (
                ('rv_student', 'StudentPass1!', 'student', self.student, '2345 6789 0124'),
                ('rv_parent', 'ParentPass1!', 'parent', self.parent, '345678901238'),
                ('rv_teacher', 'TeacherPass1!', 'teacher', self.faculty, '4567-8901-2341')):
            own = self._headers(login, password)
            resp = self._submit(own, subject_type, subject, number)
            self.assertEqual(resp.status_code, 200, resp.text)
            data = resp.json()['data']
            self.assertEqual(data['aadhar_verification_status'], 'pending')
            self.assertEqual(data['aadhaar']['status'], 'pending')
            self.assertTrue(data['aadhaar']['number_masked'].startswith('XXXX XXXX '))
            self.assertNotIn('aadhar_number', data['aadhaar'], 'The family only sees the masked number')

            pending = self.url_open('/api/v1/identity/aadhar/pending?subject_type=%s' % subject_type,
                                    headers=reviewer)
            self.assertEqual(pending.status_code, 200, pending.text)
            rows = [row for row in pending.json()['data'] if row['subject_id'] == subject.id]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['aadhar_number'], number.replace(' ', '').replace('-', ''))

            resp = self._review(reviewer, subject_type, subject, 'verify', notes='Matches the card')
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertEqual(resp.json()['data']['aadhar_verification_status'], 'verified')
            status = self.url_open('/api/v1/identity/status?subject_type=%s&subject_id=%s'
                                   % (subject_type, subject.id), headers=own).json()['data']
            self.assertEqual(status['aadhaar']['status'], 'verified')
            self.assertTrue(status['aadhaar']['verified_at'])
            self.assertEqual(status['aadhaar']['notes'], 'Matches the card')

    def test_reject_and_resubmit(self):
        own = self._headers('rv_parent', 'ParentPass1!')
        self._submit(own, 'student', self.student, '567890123458')
        resp = self._review(self._headers('rv_office', 'OfficePass1!'), 'student', self.student, 'reject',
                            notes='Number does not match the card')
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(self.student.aadhar_verification_status, 'rejected')
        resp = self._submit(own, 'student', self.student, '987654321096')
        self.assertEqual(resp.json()['data']['aadhar_verification_status'], 'pending')

    def test_review_rules(self):
        reviewer = self._headers('rv_reviewer', 'ReviewPass1!')
        resp = self._review(reviewer, 'student', self.student, 'verify')
        self.assertEqual((resp.status_code, resp.json()['error']['code']), (400, 'invalid_transition'))
        resp = self._review(reviewer, 'student', self.student, 'approve')
        self.assertEqual(resp.json()['error']['code'], 'invalid_decision')
        own = self._headers('rv_student', 'StudentPass1!')
        self._submit(own, 'student', self.student, '234567890124')
        for headers in (own, self._headers('rv_parent', 'ParentPass1!'), self._headers('rv_teacher', 'TeacherPass1!')):
            self.assertEqual(self._review(headers, 'student', self.student, 'verify').status_code, 403)
            self.assertEqual(self.url_open('/api/v1/identity/aadhar/pending', headers=headers).status_code, 403)

    def test_same_verified_number_resubmitted_stays_verified(self):
        self.student.aadhar_card = '234567890124'  # typed by the office: verified
        resp = self._submit(self._headers('rv_student', 'StudentPass1!'), 'student', self.student, '2345 6789 0124')
        self.assertEqual(resp.json()['data']['aadhar_verification_status'], 'verified')

    def test_input_variants(self):
        own = self._headers('rv_student', 'StudentPass1!')
        resp = self.url_open('/api/v1/identity/aadhar/submit', headers=own, json={
            'subject_type': 'student', 'subject_id': self.student.id, 'aadhaar_number': 234567890124})
        self.assertEqual(resp.status_code, 200, 'A JSON number and the "aadhaar_number" spelling work')
        resp = self.url_open('/api/v1/identity/status?subject_type=student&subject_id=abc', headers=own)
        self.assertEqual((resp.status_code, resp.json()['error']['code']), (400, 'invalid_subject_id'))
        resp = self._submit(own, 'student', self.student, '123456789012')
        self.assertEqual((resp.status_code, resp.json()['error']['code']), (400, 'invalid_aadhar'))

    def test_old_invalid_number(self):
        """A number stored before the format check (like the sample
        123456789012): a login can still be linked, status says it is not
        valid, and it can't be verified."""
        other_user = mail_new_test_user(self.env, login='rv_legacy', groups='base.group_portal')
        legacy = self.env['op.student'].create({
            'first_name': 'Old', 'last_name': 'Number', 'gr_no': 'RV-009', 'gender': 'f'})
        self.env.cr.execute("UPDATE op_student SET aadhar_card = '123456789012', "
                            "aadhar_verification_status = 'pending' WHERE id = %s", [legacy.id])
        legacy.invalidate_recordset()
        legacy.user_id = other_user  # no error
        reviewer = self._headers('rv_reviewer', 'ReviewPass1!')
        status = self.url_open('/api/v1/identity/status?subject_type=student&subject_id=%s' % legacy.id,
                               headers=reviewer).json()['data']['aadhaar']
        self.assertEqual((status['has_number'], status['number_valid'], status['number_masked']), (True, False, None))
        resp = self._review(reviewer, 'student', legacy, 'verify')
        self.assertEqual(resp.json()['error']['code'], 'invalid_aadhar')
        with self.assertRaises(UserError):
            legacy.action_verify_aadhar()
