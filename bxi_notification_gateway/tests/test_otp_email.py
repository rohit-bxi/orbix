# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import re
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.bxi_notification_gateway.models.otp_request import EMAIL_MAX_PER_HOUR, OTP_MAX_ATTEMPTS
from odoo.addons.mail.tests.common import mail_new_test_user


@tagged('post_install', '-at_install')
class TestBxiOtpEmail(TransactionCase):
    """Login codes sent by email (channel 'email')."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.email = 'office@otp-school.test'
        cls.user = mail_new_test_user(cls.env, login='otp_mail_user', groups='base.group_portal',
                                      email='otp.user@example.com')
        cls.Otp = cls.env['bxi.otp.request']

    def setUp(self):
        super().setUp()
        # Odoo skips SMTP in tests: record what would be sent, mark it sent.
        self.sent = []
        sent = self.sent

        def fake_send(mails, *args, **kwargs):
            for mail in mails:
                sent.append({'to': mail.email_to, 'subject': mail.subject, 'body': str(mail.body_html)})
            mails.write({'state': 'sent'})
            return True

        patcher = patch.object(type(self.env['mail.mail']), '_send', fake_send)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _code(self):
        return re.search(r'(\d{6})', self.sent[-1]['body']).group(1)

    def _age(self, seconds):
        """Make every emailed code `seconds` older."""
        self.env.cr.execute("UPDATE bxi_otp_request SET create_date = create_date - %s * interval '1 second'",
                            [seconds])
        self.Otp.invalidate_model(['create_date'])

    def test_code_emailed_hashed_and_mail_deleted(self):
        self.assertEqual(self.Otp._generate_and_email(self.user, 'otp.user@example.com'), 'sent')
        self.assertEqual(self.sent[-1]['to'], 'otp.user@example.com')
        code = self._code()
        otp = self.Otp.search([('user_id', '=', self.user.id)])
        self.assertEqual(otp.channel, 'email')
        self.assertEqual(otp.email, 'otp.user@example.com')
        self.assertFalse(otp.phone)
        self.assertNotEqual(otp.code_hash, code)
        self.assertFalse(self.env['mail.mail'].search([('email_to', '=', 'otp.user@example.com')]),
                         'The mail carrying the code does not stay in the database.')
        self.assertEqual(self.Otp._verify_for_user(self.user, code), (True, None))
        self.assertEqual(self.Otp._verify_for_user(self.user, code), (False, 'not_found'), 'One use only')

    def test_failed_send_still_deletes_the_mail(self):
        def failing_send(mails, *args, **kwargs):
            mails.write({'state': 'exception', 'failure_reason': 'no server'})
            return True

        with patch.object(type(self.env['mail.mail']), '_send', failing_send):
            self.assertEqual(self.Otp._generate_and_email(self.user, 'otp.user@example.com'), 'failed')
        self.assertFalse(self.env['mail.mail'].search([('email_to', '=', 'otp.user@example.com')]))

    def test_wrong_expired_and_too_many(self):
        self.Otp._generate_and_email(self.user, 'otp.user@example.com')
        code = self._code()
        wrong = '000000' if code != '000000' else '111111'
        self.assertEqual(self.Otp._verify_for_user(self.user, wrong), (False, 'invalid_code'))
        for _i in range(OTP_MAX_ATTEMPTS - 1):
            self.Otp._verify_for_user(self.user, wrong)
        self.assertEqual(self.Otp._verify_for_user(self.user, code), (False, 'too_many_attempts'))

        self._age(120)
        self.Otp._generate_and_email(self.user, 'otp.user@example.com')
        otp = self.Otp.search([('user_id', '=', self.user.id)], order='id desc', limit=1)
        otp.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        self.assertEqual(self.Otp._verify_for_user(self.user, self._code()), (False, 'expired'))

    def test_codes_are_per_account(self):
        other = mail_new_test_user(self.env, login='otp_mail_other', groups='base.group_portal')
        self.Otp._generate_and_email(self.user, 'otp.user@example.com')
        self.assertEqual(self.Otp._verify_for_user(other, self._code()), (False, 'not_found'))

    def test_resend_throttled(self):
        self.assertEqual(self.Otp._generate_and_email(self.user, 'otp.user@example.com'), 'sent')
        self.assertEqual(self.Otp._generate_and_email(self.user, 'otp.user@example.com'), 'throttled')
        self.assertEqual(len(self.sent), 1)
        for _i in range(EMAIL_MAX_PER_HOUR - 1):
            self._age(61)
            self.assertEqual(self.Otp._generate_and_email(self.user, 'otp.user@example.com'), 'sent')
        self._age(61)
        self.assertEqual(self.Otp._generate_and_email(self.user, 'otp.user@example.com'), 'throttled',
                         'At most %s codes an hour' % EMAIL_MAX_PER_HOUR)

    def test_sms_codes_unaffected(self):
        """A phone OTP still verifies by phone only."""
        with patch.object(type(self.env['bxi.msg91.client']), 'send_otp_sms', lambda self_, phone, code: True):
            self.Otp._generate_and_email(self.user, 'otp.user@example.com')
            email_code = self._code()
        self.assertEqual(self.Otp._verify('9000000000', email_code), (False, 'not_found'))
