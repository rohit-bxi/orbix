# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Account & Security on the back-office Teacher, Student and Parent forms:
the person's login (username, account status, one-time password state)
and the Create Login / Reset Password / Send Login Credentials / Enable /
Disable buttons. Everything goes through bxi.people.service, the same code
the office's people API uses."""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .people_service import CREDENTIAL_CHANNELS, PeopleError, is_manager

ACCOUNT_STATES = [
    ('none', 'No Login'),
    ('active', 'Active'),
    ('inactive', 'Deactivated'),
]
CHANNELS = [('email', 'Email'), ('sms', 'SMS')]
assert {key for key, _label in CHANNELS} == set(CREDENTIAL_CHANNELS)

NOT_SENT_REASONS = {
    'no_email': 'this person has no email address',
    'no_phone': 'this person has no mobile number',
    'email_not_sent': 'the email could not be sent (check the outgoing mail server)',
    'sms_not_sent': 'the SMS could not be sent (check the SMS gateway settings)',
}


def check_manager(env):
    if not is_manager(env.user):
        raise AccessError(_('Only the school office can manage logins.'))


class BxiPeopleAccountMixin(models.AbstractModel):
    """Login details of a person record that has a `user_id` (op.student,
    op.faculty, op.parent). Read from the user, never stored twice."""
    _name = 'bxi.people.account.mixin'
    _description = 'People Login Account'

    bxi_has_login = fields.Boolean(string='Has Login', compute='_compute_bxi_account')
    bxi_login = fields.Char(string='Username', compute='_compute_bxi_account')
    bxi_account_state = fields.Selection(
        ACCOUNT_STATES, string='Account Status', compute='_compute_bxi_account',
        help='Whether this person can sign in. Separate from the record status.')
    bxi_must_change_password = fields.Boolean(
        string='Must Change Password', compute='_compute_bxi_account',
        help='The password is a one-time password the person must replace at their next sign-in.')
    bxi_temp_password_expires_at = fields.Datetime(
        string='One-time Password Expires', compute='_compute_bxi_account')
    bxi_last_login = fields.Datetime(string='Last Sign-in', compute='_compute_bxi_account')

    def _compute_bxi_account(self):
        for record in self:
            user = record.user_id.sudo()
            record.bxi_has_login = bool(user)
            record.bxi_login = user.login or False
            record.bxi_account_state = ('active' if user.active else 'inactive') if user else 'none'
            record.bxi_must_change_password = user.bxi_must_change_password if user else False
            record.bxi_temp_password_expires_at = (
                user.bxi_temp_password_expires_at if user and user.bxi_must_change_password else False)
            record.bxi_last_login = user.login_date if user else False

    # -- buttons --------------------------------------------------------------------

    def action_bxi_account_wizard(self):
        """Create Login / Reset Password / Send Login Credentials (the mode
        comes from the button's context)."""
        self.ensure_one()
        check_manager(self.env)
        mode = self.env.context.get('bxi_account_mode', 'create')
        if mode != 'create' and not self.user_id:
            raise UserError(_('This person has no login yet. Create one first.'))
        titles = {'create': _('Create Login'), 'reset': _('Reset Password'), 'send': _('Send Login Credentials')}
        partner = self.env['bxi.people.service']._partner(self)
        return {
            'type': 'ir.actions.act_window',
            'name': titles[mode],
            'res_model': 'bxi.people.account.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
                'default_mode': mode,
                'default_username': self.user_id.login if self.user_id else (partner.email or False),
                'default_channel': 'email' if partner.email else 'sms',
            },
        }

    def action_bxi_enable_login(self):
        self._bxi_set_login_active(True)

    def action_bxi_disable_login(self):
        self._bxi_set_login_active(False)

    def _bxi_set_login_active(self, active):
        self.ensure_one()
        check_manager(self.env)
        user = self.user_id.sudo()
        if not user:
            raise UserError(_('This person has no login yet.'))
        service = self.env['bxi.people.service']
        try:
            service._guard_account(user)
            service._set_account_active(user, active)
        except PeopleError as exc:
            raise UserError(exc.to_text()) from None


class OpStudent(models.Model):
    _name = 'op.student'
    _inherit = ['op.student', 'bxi.people.account.mixin']


class OpFaculty(models.Model):
    _name = 'op.faculty'
    _inherit = ['op.faculty', 'bxi.people.account.mixin']


class OpParent(models.Model):
    _name = 'op.parent'
    _inherit = ['op.parent', 'bxi.people.account.mixin']


class BxiPeopleAccountWizard(models.TransientModel):
    _name = 'bxi.people.account.wizard'
    _description = 'Create Login / Reset Password / Send Login Credentials'

    res_model = fields.Selection(
        [('op.student', 'Student'), ('op.faculty', 'Teacher'), ('op.parent', 'Parent')], required=True)
    res_id = fields.Integer(required=True)
    mode = fields.Selection(
        [('create', 'Create Login'), ('reset', 'Reset Password'), ('send', 'Send Login Credentials')],
        required=True, default='create')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')
    person_name = fields.Char(string='Person', compute='_compute_person_name')
    username = fields.Char()
    password = fields.Char(
        help='Leave empty to generate one. Either way it is a one-time password: '
             'the person must choose their own at the first sign-in.')
    send_credentials = fields.Boolean(string='Send Login Credentials', default=True)
    channel = fields.Selection(CHANNELS, string='Send By', default='email')
    result_message = fields.Text(readonly=True)
    one_time_password = fields.Char(readonly=True)

    @api.depends('res_model', 'res_id')
    def _compute_person_name(self):
        for wizard in self:
            record = wizard._record()
            wizard.person_name = record.display_name if record else False

    def _record(self):
        if not self.res_model or not self.res_id:
            return None
        return self.env[self.res_model].sudo().with_context(active_test=False).browse(self.res_id).exists()

    def action_apply(self):
        self.ensure_one()
        check_manager(self.env)
        record = self._record()
        if not record:
            raise UserError(_('This person no longer exists.'))
        if self.password:
            problem = self.env['res.users']._bxi_password_problem(self.password)
            if problem:
                raise UserError(problem)
        sending = self.send_credentials or self.mode == 'send'
        channel = self.channel if sending else None
        if sending and not channel:
            raise UserError(_('Choose how to send the login credentials.'))
        service = self.env['bxi.people.service']
        try:
            delivery = self._apply(service, record, channel)
        except PeopleError as exc:
            raise UserError(exc.to_text()) from None
        result = service._deliver_credentials(record, delivery) or {}
        self.write({
            'state': 'done',
            'result_message': self._result_text(record, result),
            'one_time_password': result.get('one_time_password') or False,
            'password': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'name': dict(self._fields['mode'].selection)[self.mode],
        }

    def _apply(self, service, record, channel):
        if self.mode == 'create':
            if record.user_id:
                raise UserError(_('This person already has a login.'))
            username = (self.username or '').strip()
            if not username:
                raise UserError(_('Enter a username.'))
            return service._apply_account(record, {
                'create_login': True, 'username': username, 'password': (self.password or '').strip() or None,
                'send_credentials': bool(channel), 'channel': channel,
            })
        user = record.user_id.sudo()
        if not user:
            raise UserError(_('This person has no login yet.'))
        service._guard_account(user)
        typed = (self.password or '').strip() if self.mode == 'reset' else ''
        password = user._bxi_set_temporary_password(typed or None)
        return {'user': user, 'password': password, 'generated': not typed, 'channel': channel}

    def _result_text(self, record, result):
        login = record.user_id.sudo().login
        done = {
            'create': _('Login "%s" created.', login),
            'reset': _('A new one-time password was set for "%s". They were signed out of the app.', login),
            'send': _('A new one-time password was issued for "%s".', login),
        }[self.mode]
        if result.get('sent'):
            sent = _('The username and one-time password were sent by %s.',
                     dict(CHANNELS).get(result['channel'], result['channel']))
        elif result.get('channel'):
            sent = _('They could NOT be sent: %s.', NOT_SENT_REASONS.get(result.get('reason'), result.get('reason')))
        else:
            sent = _('Nothing was sent.')
        lines = [done, sent]
        if result.get('one_time_password'):
            lines.append(_('Give the one-time password below to the person. It is shown only now.'))
        return '\n'.join(lines)
