# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import logging
import re
from unittest.mock import patch

from odoo.tests import HttpCase, tagged

from odoo.addons.bxi_aadhaar_login.models.res_users import mask_email
from odoo.addons.bxi_identity_verification.models.aadhaar import aadhaar_hash
from odoo.addons.mail.tests.common import mail_new_test_user

STUDENT_NO = '234567890124'
TEACHER_NO = '345678901238'
PARENT_NO = '456789012341'
UNKNOWN_NO = '567890123458'
PENDING_NO = '987654321096'
SPARE_NO = '876543210988'


class AadhaarLoginCase(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.email = 'office@aadhaar-school.test'
        cls.relationship = cls.env['op.parent.relationship'].search([], limit=1) or \
            cls.env['op.parent.relationship'].create({'name': 'Guardian'})

        cls.student_user = mail_new_test_user(
            cls.env, login='aad_student', password='StudentPass1!', groups='base.group_portal',
            email='student.login@example.com')
        cls.student = cls.env['op.student'].create({
            'first_name': 'Sia', 'last_name': 'Student', 'gr_no': 'AADL-001', 'gender': 'f',
            'user_id': cls.student_user.id, 'email': 'sia.student@example.com', 'aadhar_card': STUDENT_NO,
        })
        cls.teacher_user = mail_new_test_user(
            cls.env, login='aad_teacher', password='TeacherPass1!',
            groups='base.group_user,openeducat_core.group_op_faculty', email='teacher.login@example.com')
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Tej', 'last_name': 'Teacher', 'gender': 'male', 'birth_date': '1985-01-01',
            'user_id': cls.teacher_user.id, 'aadhar_card': '3456 7890 1238',
        })
        cls.parent_user = mail_new_test_user(
            cls.env, login='aad_parent', password='ParentPass1!', groups='base.group_portal',
            email='parent.login@example.com')
        cls.parent = cls.env['op.parent'].create({
            'name': cls.parent_user.partner_id.id, 'relationship_id': cls.relationship.id,
            'user_id': cls.parent_user.id, 'student_ids': [(6, 0, cls.student.ids)],
            'email': 'parent.record@example.com', 'aadhar_card': PARENT_NO,
        })

    def setUp(self):
        super().setUp()
        # Odoo skips SMTP in tests: record what would be sent, mark it sent.
        self.sent = []
        sent = self.sent

        def fake_send(mails, *args, **kwargs):
            for mail in mails:
                sent.append({'to': mail.email_to, 'body': str(mail.body_html)})
            mails.write({'state': 'sent'})
            return True

        patcher = patch.object(type(self.env['mail.mail']), '_send', fake_send)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, url, body, headers=None):
        return self.url_open(url, json=body, method='POST', headers=headers)

    def _login(self, number, password, **extra):
        body = {'login_type': 'aadhaar', 'login': number, 'password': password}
        body.update(extra)
        return self._post('/api/v1/auth/login', body)

    def _last_code(self):
        return re.search(r'(\d{6})', self.sent[-1]['body']).group(1)

    def _age_codes(self):
        self.env.cr.execute("UPDATE bxi_otp_request SET create_date = create_date - interval '2 minutes'")
        self.env['bxi.otp.request'].invalidate_model(['create_date'])

    def _error(self, resp):
        return resp.json()['error']['code']


@tagged('post_install', '-at_install')
class TestAadhaarPasswordLogin(AadhaarLoginCase):

    def test_each_role_logs_in_with_aadhaar_and_password(self):
        for number, password, user in ((STUDENT_NO, 'StudentPass1!', self.student_user),
                                       ('3456 7890 1238', 'TeacherPass1!', self.teacher_user),
                                       ('4567-8901-2341', 'ParentPass1!', self.parent_user)):
            resp = self._login(number, password, device_name='Phone')
            self.assertEqual(resp.status_code, 200, resp.text)
            data = resp.json()['data']
            self.assertEqual(data['user']['id'], user.id)
            self.assertEqual(data['auth_method'], 'password')
            self.assertEqual(data['login_identifier'], 'aadhaar')
            token = self.env['bxi.api.token'].search([('user_id', '=', user.id)], order='id desc', limit=1)
            self.assertEqual(token.login_identifier, 'aadhaar')
            self.assertEqual(token.name, 'Phone')
            self.assertFalse(token.step_up_required, 'As strong as a password login.')

    def test_aadhaar_detected_without_login_type(self):
        resp = self._post('/api/v1/auth/login', {'login': '2345 6789 0124', 'password': 'StudentPass1!'})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['user']['id'], self.student_user.id)

    def test_username_login_unchanged(self):
        resp = self._post('/api/v1/auth/login', {'login': 'aad_teacher', 'password': 'TeacherPass1!'})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotIn('login_identifier', resp.json()['data'])
        token = self.env['bxi.api.token'].search([('user_id', '=', self.teacher_user.id)], order='id desc', limit=1)
        self.assertFalse(token.login_identifier)

    def test_a_username_that_looks_like_aadhaar_stays_a_username(self):
        user = mail_new_test_user(self.env, login=SPARE_NO, password='DigitsPass1!', groups='base.group_portal')
        resp = self._post('/api/v1/auth/login', {'login': SPARE_NO, 'password': 'DigitsPass1!'})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['user']['id'], user.id)

    def test_wrong_password_and_unknown_number_look_the_same(self):
        wrong = self._login(STUDENT_NO, 'WrongPass1!')
        unknown = self._login(UNKNOWN_NO, 'StudentPass1!')
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(wrong.json(), unknown.json())
        self.assertEqual(self._error(wrong), 'invalid_credentials')

    def test_invalid_number_and_missing_fields(self):
        resp = self._login('234567890125', 'StudentPass1!')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._error(resp), 'invalid_aadhaar')
        resp = self._login(STUDENT_NO, '')
        self.assertEqual(self._error(resp), 'missing_credentials')

    def test_pending_number_needs_review(self):
        self.student._submit_aadhar(PENDING_NO)
        self.assertEqual(self._login(PENDING_NO, 'StudentPass1!').status_code, 401)
        self.company.bxi_aadhaar_login_requires_verified = False
        self.assertEqual(self._login(PENDING_NO, 'StudentPass1!').status_code, 200)
        self.company.bxi_aadhaar_login_requires_verified = True
        self.student.action_verify_aadhar()
        self.assertEqual(self._login(PENDING_NO, 'StudentPass1!').status_code, 200)

    def test_rejected_number_refused(self):
        self.student._submit_aadhar(PENDING_NO)
        self.student.action_reject_aadhar()
        self.company.bxi_aadhaar_login_requires_verified = False
        self.assertEqual(self._login(PENDING_NO, 'StudentPass1!').status_code, 401,
                         'A rejected number never logs in, even when unverified numbers may.')

    def test_settings_switch_roles_and_feature(self):
        self.company.bxi_aadhaar_login_allow_teacher = False
        self.assertEqual(self._login(TEACHER_NO, 'TeacherPass1!').status_code, 401)
        self.assertEqual(self._login(STUDENT_NO, 'StudentPass1!').status_code, 200)
        self.company.bxi_aadhaar_login_enabled = False
        self.assertEqual(self._login(STUDENT_NO, 'StudentPass1!').status_code, 401)

    def test_archived_login_or_record_refused(self):
        self.student.active = False
        self.assertEqual(self._login(STUDENT_NO, 'StudentPass1!').status_code, 401)
        self.student.active = True
        self.parent_user.active = False
        self.assertEqual(self._login(PARENT_NO, 'ParentPass1!').status_code, 401)

    def test_number_on_two_different_accounts_refused(self):
        """Old data the constraint never saw: the same number on two
        different logins. Login is refused until the office fixes it."""
        other_user = mail_new_test_user(self.env, login='aad_dup', password='DupPass1!', groups='base.group_portal')
        other = self.env['op.student'].create({
            'first_name': 'Dup', 'last_name': 'Student', 'gr_no': 'AADL-009', 'gender': 'm',
            'user_id': other_user.id,
        })
        self.env.cr.execute(
            "UPDATE op_student SET aadhar_card = %s, bxi_aadhaar_hash = %s, bxi_aadhaar_last4 = '0124', "
            "aadhar_verification_status = 'verified' WHERE id = %s",
            [STUDENT_NO, aadhaar_hash(self.env, STUDENT_NO), other.id])
        self.env['op.student'].invalidate_model()
        resp = self._login(STUDENT_NO, 'StudentPass1!')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self._error(resp), 'ambiguous_aadhaar')
        resp = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': STUDENT_NO})
        self.assertEqual(resp.status_code, 409)

    def test_number_never_logged(self):
        logger = logging.getLogger('odoo')
        records = []

        class Collect(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler = Collect(level=logging.DEBUG)
        logger.addHandler(handler)
        old_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            self._login(STUDENT_NO, 'WrongPass1!')
            self._login(UNKNOWN_NO, 'WrongPass1!')
            self._login(STUDENT_NO, 'StudentPass1!')
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)
        self.assertTrue(any('aad_student' in message for message in records), records)
        for number in (STUDENT_NO, UNKNOWN_NO):
            self.assertFalse([m for m in records if number in m], 'The Aadhaar number is never logged.')

    def test_profile_shows_aadhaar_login(self):
        token = self._login(STUDENT_NO, 'StudentPass1!').json()['data']['token']
        me = self.url_open('/api/v1/auth/me', headers={'Authorization': 'Bearer %s' % token})
        self.assertEqual(me.json()['data']['aadhaar_login'], {'available': True, 'last4': '0124'})
        token = self._post('/api/v1/auth/login', {'login': 'aad_teacher',
                                                  'password': 'TeacherPass1!'}).json()['data']['token']
        self.company.bxi_aadhaar_login_allow_teacher = False
        me = self.url_open('/api/v1/auth/me', headers={'Authorization': 'Bearer %s' % token})
        self.assertEqual(me.json()['data']['aadhaar_login'], {'available': False, 'last4': None})


@tagged('post_install', '-at_install')
class TestAadhaarEmailCodeLogin(AadhaarLoginCase):

    def test_code_login_for_each_role(self):
        for number, user, email in ((STUDENT_NO, self.student_user, 'sia.student@example.com'),
                                    (TEACHER_NO, self.teacher_user, 'teacher.login@example.com'),
                                    (PARENT_NO, self.parent_user, 'parent.record@example.com')):
            resp = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': number})
            self.assertEqual(resp.status_code, 200, resp.text)
            data = resp.json()['data']
            self.assertEqual(data, {'sent': True, 'channel': 'email', 'email_hint': mask_email(email),
                                    'expires_in': 600})
            self.assertEqual(self.sent[-1]['to'], email)
            resp = self._post('/api/v1/auth/aadhaar/otp-login',
                              {'aadhaar': number, 'otp': self._last_code(), 'device_name': 'Tablet'})
            self.assertEqual(resp.status_code, 200, resp.text)
            data = resp.json()['data']
            self.assertEqual(data['user']['id'], user.id)
            self.assertEqual(data['auth_method'], 'otp')
            self.assertEqual(data['login_identifier'], 'aadhaar')
            token = self.env['bxi.api.token'].search([('user_id', '=', user.id)], order='id desc', limit=1)
            self.assertEqual((token.auth_method, token.login_identifier), ('otp', 'aadhaar'))

    def test_student_without_email_uses_parent_email(self):
        user = mail_new_test_user(self.env, login='aad_kid', password='KidPass1!', groups='base.group_portal')
        user.partner_id.email = False
        kid = self.env['op.student'].create({
            'first_name': 'Kid', 'last_name': 'NoMail', 'gr_no': 'AADL-010', 'gender': 'm',
            'user_id': user.id, 'aadhar_card': SPARE_NO,
        })
        self.parent.student_ids = [(4, kid.id)]
        resp = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': SPARE_NO})
        self.assertEqual(resp.json()['data']['email_hint'], mask_email('parent.record@example.com'))
        self.assertEqual(self.sent[-1]['to'], 'parent.record@example.com')

    def test_unknown_number_gets_the_same_reply_and_no_email(self):
        first = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': UNKNOWN_NO}).json()['data']
        again = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': UNKNOWN_NO}).json()['data']
        self.assertEqual(first, again, 'A stable made-up hint')
        self.assertEqual(set(first), {'sent', 'channel', 'email_hint', 'expires_in'})
        self.assertTrue(first['sent'])
        self.assertRegex(first['email_hint'], r'^\w\*\*\*@\w\*\*\*\.com$')
        self.assertFalse(self.sent)
        resp = self._post('/api/v1/auth/aadhaar/otp-login', {'aadhaar': UNKNOWN_NO, 'otp': '123456'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._error(resp), 'not_found', 'Same as a real account that never asked for a code')

    def test_wrong_reused_and_too_many_codes(self):
        self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': STUDENT_NO})
        code = self._last_code()
        wrong = '000000' if code != '000000' else '111111'
        resp = self._post('/api/v1/auth/aadhaar/otp-login', {'aadhaar': STUDENT_NO, 'otp': wrong})
        self.assertEqual((resp.status_code, self._error(resp)), (400, 'invalid_code'))
        resp = self._post('/api/v1/auth/aadhaar/otp-login', {'aadhaar': STUDENT_NO, 'otp': code})
        self.assertEqual(resp.status_code, 200, resp.text)
        resp = self._post('/api/v1/auth/aadhaar/otp-login', {'aadhaar': STUDENT_NO, 'otp': code})
        self.assertEqual(self._error(resp), 'not_found', 'A code works once')

        self._age_codes()
        self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': STUDENT_NO})
        code = self._last_code()
        for _i in range(5):
            self._post('/api/v1/auth/aadhaar/otp-login', {'aadhaar': STUDENT_NO, 'otp': wrong})
        resp = self._post('/api/v1/auth/aadhaar/otp-login', {'aadhaar': STUDENT_NO, 'otp': code})
        self.assertEqual(self._error(resp), 'too_many_attempts')

    def test_code_is_tied_to_its_account(self):
        self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': STUDENT_NO})
        resp = self._post('/api/v1/auth/aadhaar/otp-login', {'aadhaar': TEACHER_NO, 'otp': self._last_code()})
        self.assertEqual(self._error(resp), 'not_found')

    def test_resend_is_throttled(self):
        self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': STUDENT_NO})
        first = self._last_code()
        resp = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': STUDENT_NO})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self.sent), 1, 'No second email within a minute')
        resp = self._post('/api/v1/auth/aadhaar/otp-login', {'aadhaar': STUDENT_NO, 'otp': first})
        self.assertEqual(resp.status_code, 200, 'The first code is still the one to use')

    def test_email_code_switched_off(self):
        # /config answers for the whole database (any company offering it),
        # so switch the email code off everywhere, not just here: the
        # database may hold other companies with it on.
        self.env['res.company'].sudo().search([]).bxi_aadhaar_login_otp_enabled = False
        resp = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': STUDENT_NO})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(self.sent)
        config = self.url_open('/api/v1/auth/aadhaar/config').json()['data']
        self.assertEqual((config['enabled'], config['otp_enabled']), (True, False))
        self.assertEqual(self._login(STUDENT_NO, 'StudentPass1!').status_code, 200, 'Password still works')

    def test_validation(self):
        resp = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': '1234'})
        self.assertEqual(self._error(resp), 'invalid_aadhaar')
        resp = self._post('/api/v1/auth/aadhaar/otp-login', {'aadhaar': STUDENT_NO})
        self.assertEqual(self._error(resp), 'missing_fields')

    def test_code_mail_not_kept(self):
        self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': STUDENT_NO})
        self.assertFalse(self.env['mail.mail'].search([('email_to', '=', 'sia.student@example.com')]))
        otp = self.env['bxi.otp.request'].search([('user_id', '=', self.student_user.id)])
        self.assertNotEqual(otp.code_hash, self._last_code())


@tagged('post_install', '-at_install')
class TestAadhaarOtpInResponse(AadhaarLoginCase):
    """The testing switch that returns the login code in the API reply."""

    def _switch(self, on):
        self.env['ir.config_parameter'].sudo().set_param('bxi_aadhaar_login.otp_in_response', 'True' if on else 'False')

    def test_off_by_default(self):
        self.assertFalse(self.env['ir.config_parameter'].sudo().get_param('bxi_aadhaar_login.otp_in_response'))
        data = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': STUDENT_NO}).json()['data']
        self.assertNotIn('otp', data)

    def test_code_returned_and_logs_in(self):
        self._switch(True)
        with self.assertLogs('odoo.addons.bxi_aadhaar_login.controllers.api', level='WARNING'):
            data = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': STUDENT_NO}).json()['data']
        self.assertRegex(data['otp'], r'^\d{6}$')
        self.assertEqual(data['otp'], self._last_code(), 'The same code as the email')
        resp = self._post('/api/v1/auth/aadhaar/otp-login', {'aadhaar': STUDENT_NO, 'otp': data['otp']})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['user']['id'], self.student_user.id)

    def test_works_without_an_email_address(self):
        self._switch(True)
        user = mail_new_test_user(self.env, login='aad_nomail', password='NoMailPass1!', groups='base.group_portal')
        user.partner_id.email = False
        self.env['op.student'].create({
            'first_name': 'No', 'last_name': 'Mail', 'gr_no': 'AADL-020', 'gender': 'm',
            'user_id': user.id, 'aadhar_card': SPARE_NO,
        })
        data = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': SPARE_NO}).json()['data']
        self.assertTrue(data['otp'])
        self.assertFalse(self.sent, 'Nothing to email')
        resp = self._post('/api/v1/auth/aadhaar/otp-login', {'aadhaar': SPARE_NO, 'otp': data['otp']})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_unknown_number_and_throttled_resend_give_null(self):
        self._switch(True)
        data = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': UNKNOWN_NO}).json()['data']
        self.assertIn('otp', data)
        self.assertIsNone(data['otp'])
        self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': STUDENT_NO})
        again = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': STUDENT_NO}).json()['data']
        self.assertIsNone(again['otp'], 'Within a minute the previous code is still the one to use')

    def test_switch_off_again_hides_the_code(self):
        self._switch(True)
        self._switch(False)
        data = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': STUDENT_NO}).json()['data']
        self.assertNotIn('otp', data)


@tagged('post_install', '-at_install')
class TestAadhaarStaffLogin(AadhaarLoginCase):
    """Administrators / office staff: the number sits on their employee record."""

    ADMIN_NO = '765432109878'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin_user = mail_new_test_user(
            cls.env, login='aad_admin_staff', password='AdminPass1!', groups='base.group_user,base.group_system',
            email='admin.login@example.com')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Asha Admin', 'user_id': cls.admin_user.id, 'work_email': 'asha.work@example.com',
            'aadhar_card': '7654 3210 9878',
        })

    def test_staff_off_by_default(self):
        self.assertFalse(self.company.bxi_aadhaar_login_allow_staff)
        self.assertEqual(self.employee.aadhar_verification_status, 'verified')
        self.assertEqual(self._login(self.ADMIN_NO, 'AdminPass1!').status_code, 401)

    def test_admin_logs_in_with_aadhaar_password_and_email_code(self):
        self.company.bxi_aadhaar_login_allow_staff = True
        resp = self._login('7654 3210 9878', 'AdminPass1!')
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertEqual(data['user']['id'], self.admin_user.id)
        self.assertTrue(data['user']['is_admin'])
        self.assertEqual(data['user']['aadhaar_login'], {'available': True, 'last4': '9878'})

        resp = self._post('/api/v1/auth/aadhaar/otp-request', {'aadhaar': self.ADMIN_NO})
        self.assertEqual(resp.json()['data']['email_hint'], mask_email('asha.work@example.com'))
        self.assertEqual(self.sent[-1]['to'], 'asha.work@example.com')
        resp = self._post('/api/v1/auth/aadhaar/otp-login', {'aadhaar': self.ADMIN_NO, 'otp': self._last_code()})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['user']['id'], self.admin_user.id)

    def test_staff_number_cannot_belong_to_someone_else(self):
        with self.assertRaises(Exception):
            self.student.write({'aadhar_card': self.ADMIN_NO})

    def test_staff_role_in_settings_api(self):
        headers = {'Authorization': 'Bearer %s' % self._post('/api/v1/auth/login', {
            'login': 'aad_admin_staff', 'password': 'AdminPass1!'}).json()['data']['token']}
        resp = self._post('/api/v1/admin/aadhaar-login/settings',
                          {'roles': ['student', 'teacher', 'parent', 'staff']}, headers=headers)
        self.assertEqual(resp.json()['data']['roles'], ['student', 'teacher', 'parent', 'staff'])
        self.assertTrue(self.company.bxi_aadhaar_login_allow_staff)
        self.assertEqual(self._login(self.ADMIN_NO, 'AdminPass1!').status_code, 200)


@tagged('post_install', '-at_install')
class TestAadhaarLoginSettingsApi(AadhaarLoginCase):

    def _token(self, login, password):
        resp = self._post('/api/v1/auth/login', {'login': login, 'password': password})
        return {'Authorization': 'Bearer %s' % resp.json()['data']['token']}

    def test_admin_reads_and_changes_settings(self):
        admin = mail_new_test_user(self.env, login='aad_admin', password='AdminPass1!',
                                   groups='base.group_user,base.group_system')
        headers = self._token('aad_admin', 'AdminPass1!')
        resp = self.url_open('/api/v1/admin/aadhaar-login/settings', headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['roles'], ['student', 'teacher', 'parent'])
        resp = self._post('/api/v1/admin/aadhaar-login/settings',
                          {'otp_enabled': False, 'roles': ['student', 'parent']}, headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertEqual((data['otp_enabled'], data['roles']), (False, ['student', 'parent']))
        self.assertFalse(admin.company_id.bxi_aadhaar_login_allow_teacher)
        self.assertFalse(data['otp_in_response'])
        resp = self._post('/api/v1/admin/aadhaar-login/settings', {'otp_in_response': True}, headers=headers)
        self.assertTrue(resp.json()['data']['otp_in_response'])
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('bxi_aadhaar_login.otp_in_response'), 'True')
        resp = self._post('/api/v1/admin/aadhaar-login/settings', {'otp_in_response': 'yes'}, headers=headers)
        self.assertEqual(self._error(resp), 'invalid_otp_in_response')
        resp = self._post('/api/v1/admin/aadhaar-login/settings', {'roles': ['visitor']}, headers=headers)
        self.assertEqual(self._error(resp), 'invalid_roles')
        resp = self._post('/api/v1/admin/aadhaar-login/settings', {'enabled': 'yes'}, headers=headers)
        self.assertEqual(self._error(resp), 'invalid_enabled')

    def test_non_admin_forbidden(self):
        headers = self._token('aad_teacher', 'TeacherPass1!')
        self.assertEqual(self.url_open('/api/v1/admin/aadhaar-login/settings', headers=headers).status_code, 403)
        resp = self._post('/api/v1/admin/aadhaar-login/settings', {'enabled': False}, headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(self.company.bxi_aadhaar_login_enabled)


@tagged('post_install', '-at_install')
class TestAadhaarWebLogin(AadhaarLoginCase):

    def _csrf(self, url):
        page = self.url_open(url)
        self.assertEqual(page.status_code, 200)
        return re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1), page

    def _assert_signed_in(self, user):
        user.invalidate_recordset(['login_date'])
        self.assertTrue(user.login_date, 'Odoo recorded the sign-in of this account')
        page = self.url_open('/my', allow_redirects=False)
        self.assertEqual(page.status_code, 200, 'The browser session is signed in')

    def test_login_page_offers_aadhaar(self):
        _csrf, page = self._csrf('/web/login')
        self.assertIn('Email, username or Aadhaar number', page.text)
        self.assertIn('/web/login/aadhaar-code', page.text)

    def test_password_login_with_aadhaar(self):
        csrf, _page = self._csrf('/web/login')
        resp = self.url_open('/web/login', data={
            'login': '2345 6789 0124', 'password': 'StudentPass1!', 'csrf_token': csrf}, allow_redirects=False)
        self.assertIn(resp.status_code, (302, 303), resp.text[:500])
        self._assert_signed_in(self.student_user)

    def test_failed_web_login_keeps_the_typed_number(self):
        csrf, _page = self._csrf('/web/login')
        resp = self.url_open('/web/login', data={
            'login': STUDENT_NO, 'password': 'WrongPass1!', 'csrf_token': csrf})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Wrong login/password', resp.text)
        self.assertIn(STUDENT_NO, resp.text)
        self.assertNotIn('aad_student', resp.text, 'The username behind the number is not revealed.')

    def test_email_code_web_login(self):
        csrf, _page = self._csrf('/web/login/aadhaar-code')
        resp = self.url_open('/web/login/aadhaar-code', data={
            'step': 'request', 'aadhaar': '4567 8901 2341', 'csrf_token': csrf})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(mask_email('parent.record@example.com'), resp.text)
        self.assertIn('name="otp"', resp.text)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', resp.text).group(1)

        resp = self.url_open('/web/login/aadhaar-code', data={'step': 'verify', 'otp': '999999' if
                                                              self._last_code() != '999999' else '888888',
                                                              'csrf_token': csrf})
        self.assertIn('The code is not correct.', resp.text)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', resp.text).group(1)
        resp = self.url_open('/web/login/aadhaar-code', data={
            'step': 'verify', 'otp': self._last_code(), 'csrf_token': csrf}, allow_redirects=False)
        self.assertIn(resp.status_code, (302, 303), resp.text[:500])
        self._assert_signed_in(self.parent_user)

    def test_email_code_web_login_unknown_number(self):
        csrf, _page = self._csrf('/web/login/aadhaar-code')
        resp = self.url_open('/web/login/aadhaar-code', data={
            'step': 'request', 'aadhaar': UNKNOWN_NO, 'csrf_token': csrf})
        self.assertIn('name="otp"', resp.text, 'Same next screen as a registered number')
        self.assertFalse(self.sent)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', resp.text).group(1)
        resp = self.url_open('/web/login/aadhaar-code', data={'step': 'verify', 'otp': '123456', 'csrf_token': csrf})
        self.assertIn('The code is not correct.', resp.text)
