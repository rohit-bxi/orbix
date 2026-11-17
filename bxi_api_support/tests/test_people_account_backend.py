# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged('post_install', '-at_install')
class TestPeopleAccountBackend(TransactionCase):
    """Account & Security tab on the Student / Teacher / Parent forms: the
    login fields and the Create Login / Reset Password / Send Login
    Credentials / Enable / Disable buttons."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.office = mail_new_test_user(
            cls.env, login='pab_office', groups='base.group_user,openeducat_core.group_op_back_office_admin')
        cls.clerk = mail_new_test_user(cls.env, login='pab_clerk', groups='base.group_user')
        cls.student = cls.env['op.student'].create({
            'first_name': 'Bea', 'last_name': 'Backend', 'gender': 'f', 'email': 'bea.backend@pab.test'})
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Tom', 'last_name': 'Backend', 'gender': 'male', 'birth_date': '1985-01-01'})
        cls.env.company.email = 'office@pab.test'

    def setUp(self):
        super().setUp()
        self.sent_mails = []

        def fake_send(mails, *args, **kwargs):
            self.sent_mails.extend(mail.email_to for mail in mails)
            mails.write({'state': 'sent'})
            return True

        patcher = patch.object(type(self.env['mail.mail']), '_send', fake_send)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _wizard(self, record, mode, **vals):
        action = record.with_user(self.office).with_context(bxi_account_mode=mode).action_bxi_account_wizard()
        context = dict(action['context'])
        wizard = self.env['bxi.people.account.wizard'].with_user(self.office).with_context(context).create(vals)
        return wizard, action

    def test_no_login_yet(self):
        self.assertEqual(self.student.bxi_account_state, 'none')
        self.assertFalse(self.student.bxi_has_login)
        with self.assertRaises(UserError):
            self.student.with_user(self.office).with_context(bxi_account_mode='reset').action_bxi_account_wizard()

    def test_create_login_send_by_email(self):
        wizard, action = self._wizard(self.student, 'create', password='BeaTyped99')
        self.assertEqual(action['context']['default_username'], 'bea.backend@pab.test',
                         'The username is suggested from the email.')
        wizard.username = 'bea.backend'
        wizard.action_apply()
        self.assertEqual(wizard.state, 'done')
        self.assertIn('sent by Email', wizard.result_message)
        self.assertFalse(wizard.one_time_password, 'Typed and sent: nothing to show.')
        self.assertFalse(wizard.password, 'The typed password is not kept on the wizard.')
        self.assertEqual(self.sent_mails[-1], 'bea.backend@pab.test', 'The credentials email.')
        self.student.invalidate_recordset()
        self.assertEqual(self.student.bxi_login, 'bea.backend')
        self.assertEqual(self.student.bxi_account_state, 'active')
        self.assertTrue(self.student.bxi_must_change_password)
        self.assertTrue(self.student.bxi_temp_password_expires_at)
        self.assertTrue(self.student.user_id.has_group('base.group_portal'))

    def test_teacher_login_generated_password_reset_and_status(self):
        wizard, _action = self._wizard(self.faculty, 'create', username='tom.backend', send_credentials=False)
        wizard.action_apply()
        self.assertTrue(wizard.one_time_password, 'Generated and not sent: shown once.')
        user = self.faculty.user_id
        self.assertTrue(user.has_group('openeducat_core.group_op_faculty'))

        # A teacher without email: sending fails, the new password is shown.
        wizard, _action = self._wizard(self.faculty, 'send', channel='email')
        wizard.action_apply()
        self.assertIn('could NOT be sent', wizard.result_message)
        self.assertTrue(wizard.one_time_password)

        wizard, _action = self._wizard(self.faculty, 'reset', password='short', send_credentials=False)
        with self.assertRaises(UserError):
            wizard.action_apply()

        self.faculty.with_user(self.office).action_bxi_disable_login()
        self.faculty.invalidate_recordset()
        self.assertEqual(self.faculty.bxi_account_state, 'inactive')
        self.assertFalse(user.active)
        self.faculty.with_user(self.office).action_bxi_enable_login()
        self.faculty.invalidate_recordset()
        self.assertEqual(self.faculty.bxi_account_state, 'active')

    def test_taken_username(self):
        wizard, _action = self._wizard(self.student, 'create', username='admin', password='BeaTyped99',
                                       send_credentials=False)
        with self.assertRaises(UserError):
            wizard.action_apply()

    def test_only_the_office(self):
        with self.assertRaises(AccessError):
            self.student.with_user(self.clerk).with_context(bxi_account_mode='create').action_bxi_account_wizard()
        with self.assertRaises(AccessError):
            self.faculty.with_user(self.clerk).action_bxi_disable_login()

    def test_cannot_deactivate_own_login(self):
        self.faculty.user_id = self.office
        with self.assertRaises(UserError):
            self.faculty.with_user(self.office).action_bxi_disable_login()
