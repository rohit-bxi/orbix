# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Account & Security for the office's teacher / student / parent screens:
creating a person's login, one-time passwords, sending credentials and the
face-recognition hook (implemented by bxi_face_auth)."""
import json
import logging

from markupsafe import Markup, escape

from odoo import _, api, models

from odoo.addons.bxi_api.controllers.auth import api_error

_logger = logging.getLogger(__name__)

ROLE_MODELS = {'teacher': 'op.faculty', 'student': 'op.student', 'parent': 'op.parent'}
CREDENTIAL_CHANNELS = ('email', 'sms')
# Who may add and edit people records and their logins (API and back office).
MANAGER_GROUPS = (
    'openeducat_core.group_op_back_office_admin',
    'bxi_academic_management.group_academic_manager',
    'base.group_system',
)


def is_manager(user):
    return any(user.has_group(group) for group in MANAGER_GROUPS)


class PeopleError(Exception):
    """Bad input found while a people create/update is half-way through
    its transaction: raised so the savepoint rolls everything back, then
    turned into the API error envelope by the controller. `response` is a
    ready-made error response (e.g. from the face engine) to use as is."""

    def __init__(self, message, code, status=400, response=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.response = response

    def to_response(self):
        return self.response or api_error(self.message, status=self.status, code=self.code)

    def to_text(self):
        """The message for a back-office dialog (a ready-made response
        carries it in its JSON body)."""
        if self.message:
            return self.message
        try:
            return json.loads(self.response.get_data())['error']['message']
        except Exception:  # noqa: BLE001 - any unreadable response gets the generic text
            return _('The request could not be completed.')


class BxiPeopleService(models.AbstractModel):
    _name = 'bxi.people.service'
    _description = 'People Account Service'

    # -- records --------------------------------------------------------------------

    @api.model
    def _role_of(self, record):
        return {model: role for role, model in ROLE_MODELS.items()}[record._name]

    @api.model
    def _partner(self, record):
        return record.name if record._name == 'op.parent' else record.partner_id

    @api.model
    def _phone(self, record):
        partner = self._partner(record)
        return (record._name == 'op.parent' and record.mobile) or partner.phone or False

    # -- logins ---------------------------------------------------------------------

    @api.model
    def _login_taken(self, login, user=None):
        domain = [('login', '=ilike', login)]
        if user:
            domain.append(('id', '!=', user.id))
        return bool(self.env['res.users'].sudo().with_context(active_test=False).search_count(domain, limit=1))

    @api.model
    def _user_vals(self, record, login):
        partner = self._partner(record)
        vals = {
            'name': partner.name,
            'login': login,
            'partner_id': partner.id,
            'tz': self.env.context.get('tz') or self.env.user.tz or False,
        }
        role = self._role_of(record)
        if role == 'teacher':
            vals.update({
                'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                      self.env.ref('openeducat_core.group_op_faculty').id])],
                'dept_id': record.main_department_id.id or False,
                'department_ids': [(6, 0, record.allowed_department_ids.ids)],
            })
        elif role == 'student':
            vals.update({'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])], 'is_student': True})
        else:
            template = self.env.ref('openeducat_parent.parent_template_user', raise_if_not_found=False)
            groups = template.group_ids if template else self.env.ref('base.group_portal')
            vals.update({
                'group_ids': [(6, 0, groups.ids)],
                'is_parent': True,
                'child_ids': [(6, 0, record.student_ids.user_id.ids)],
            })
        return vals

    @api.model
    def _create_login(self, record, login):
        """Give `record` a login named `login` - the same groups the
        backend's "Create User" buttons give - or reuse the account already
        attached to its contact. A teacher also gets their HR employee
        (leave, attendance and the designation live there)."""
        partner = self._partner(record)
        Users = self.env['res.users'].sudo().with_context(no_reset_password=True, active_test=False)
        user = Users.search([('partner_id', '=', partner.id)], limit=1)
        if self._login_taken(login, user):
            raise PeopleError(_('This username is already taken.'), 'login_taken', status=409)
        if user:
            user.write({'login': login, 'active': True})
        else:
            user = Users.create(self._user_vals(record, login))
        record.sudo().user_id = user
        role = self._role_of(record)
        if role == 'parent':
            # openeducat_parent keeps the parent's user on its contact too.
            partner.sudo().user_id = user
        elif role == 'teacher' and not record.emp_id:
            record.sudo().create_employee()
        return user

    @api.model
    def _guard_account(self, user):
        """Only an administrator may change an administrator's login."""
        if user and user.has_group('base.group_system') and not self.env.user.has_group('base.group_system'):
            raise PeopleError(_("Only an administrator can change an administrator's login."), 'forbidden',
                              status=403)

    @api.model
    def _set_account_active(self, user, active):
        """Account Status: whether `user` can sign in. Turning it off also
        ends every app session."""
        if not active and user == self.env.user:
            raise PeopleError(_("You can't deactivate your own login."), 'cannot_deactivate_self')
        user.sudo().active = active
        if not active:
            self.env['bxi.api.token'].sudo()._revoke_all_for_user(user)

    @api.model
    def _apply_account(self, record, account):
        """Create/update the person's login from a parsed account block
        ({create_login, username?, password?, active?, send_credentials?,
        channel?}). Returns the credentials still to deliver once the
        transaction succeeded ({user, password, generated, channel}) or
        None."""
        if not account:
            return None
        user = record.user_id.sudo()
        self._guard_account(user)
        password, generated = None, False
        if not user:
            if not account['create_login']:
                raise PeopleError(_('This person has no login yet: send account.create_login true.'), 'no_account')
            login = account.get('username') or self._partner(record).email
            if not login:
                raise PeopleError(_('account.username is required.'), 'missing_username')
            user = self._create_login(record, login.strip())
            password = user._bxi_set_temporary_password(account.get('password'))
            generated = not account.get('password')
        else:
            if account.get('username') and account['username'] != user.login:
                if self._login_taken(account['username'], user):
                    raise PeopleError(_('This username is already taken.'), 'login_taken', status=409)
                user.write({'login': account['username']})
            if account.get('password'):
                password = user._bxi_set_temporary_password(account['password'])
        if 'active' in account and account['active'] != user.active:
            self._set_account_active(user, account['active'])
        if account.get('send_credentials'):
            if not password:
                password, generated = user._bxi_set_temporary_password(), True
            return {'user': user, 'password': password, 'generated': generated, 'channel': account['channel']}
        if generated:
            return {'user': user, 'password': password, 'generated': True, 'channel': None}
        return None

    @api.model
    def _deliver_credentials(self, record, delivery):
        """Send pending credentials (after the transaction succeeded) and
        describe the outcome: {channel, sent, reason, one_time_password?}."""
        if not delivery:
            return None
        if delivery['channel']:
            result = self._send_credentials(record, delivery['user'], delivery['password'], delivery['channel'])
        else:
            result = {'channel': None, 'sent': False, 'reason': 'not_requested'}
        if delivery['generated'] and not result['sent']:
            # Shown once, so the office can hand it over in person.
            result['one_time_password'] = delivery['password']
        return result

    # -- credentials ----------------------------------------------------------------

    @api.model
    def _send_credentials(self, record, user, password, channel):
        """Send `user`'s username and one-time password. Never raises: a
        send that failed comes back as {'sent': False, 'reason': ...}."""
        if channel == 'sms':
            # While SMS is not set up (Settings > Orbix Notifications), an
            # SMS request goes out by email instead; "SMS and email" sends
            # both and reports the SMS.
            channels = self.env['bxi.otp.request'].sudo()._delivery_channels('credentials')
            sms_result = None
            if 'sms' in channels:
                phone = self._phone(record)
                if not phone:
                    sms_result = {'channel': 'sms', 'sent': False, 'reason': 'no_phone'}
                else:
                    sent = self.env['bxi.msg91.client'].sudo().send_credentials_sms(phone, user.login, password)
                    sms_result = {'channel': 'sms', 'sent': sent, 'reason': None if sent else 'sms_not_sent'}
                if 'email' not in channels:
                    return sms_result
            email_result = self._send_credentials_email(record, user, password)
            if sms_result and (sms_result['sent'] or not email_result['sent']):
                return sms_result
            return dict(email_result, requested_channel='sms')
        return self._send_credentials_email(record, user, password)

    @api.model
    def _send_credentials_email(self, record, user, password):
        channel = 'email'
        email = self._partner(record).email or user.email
        if not email:
            return {'channel': channel, 'sent': False, 'reason': 'no_email'}
        company = user.company_id or self.env.company
        body = Markup(
            '<p>Hello %(name)s,</p>'
            '<p>Your %(school)s login for the Orbix app:</p>'
            '<p>Username: <strong>%(login)s</strong><br/>One-time password: <strong>%(password)s</strong></p>'
            '<p>You will be asked to choose your own password when you sign in. '
            'The one-time password stops working if it is not used soon.</p>'
        ) % {'name': escape(user.name), 'school': escape(company.name), 'login': escape(user.login),
             'password': escape(password)}
        mail = self.env['mail.mail'].sudo().create({
            'subject': _('Your %s login', company.name),
            'email_to': email,
            'email_from': self.env['bxi.otp.request']._bxi_email_sender(company)
            or self.env.user.email_formatted or False,
            'body_html': body,
            'auto_delete': True,
        })
        try:
            mail.send(raise_exception=False)
        except Exception:  # noqa: BLE001 - a mail server problem must not undo the account
            _logger.exception('Sending login credentials to %s failed.', email)
        sent = not mail.exists() or mail.state == 'sent'
        if not sent:
            _logger.warning('Login credentials email to %s not sent: %s', email, mail.failure_reason or mail.state)
        if mail.exists():
            # Never keep a plain-text password in the database, sent or not
            # (auto_delete alone leaves failed mails in the queue).
            mail.unlink()
        return {'channel': channel, 'sent': sent, 'reason': None if sent else 'email_not_sent'}

    # -- face recognition (implemented by bxi_face_auth) -------------------------------

    @api.model
    def _face_available(self):
        return False

    @api.model
    def _apply_face(self, record, user, face):
        """Turn face recognition on (enrolling `face`'s photo) or off for
        `user`. Raises PeopleError on bad input."""
        if face.get('enabled'):
            raise PeopleError(_('Face recognition is not installed on this server.'), 'face_unavailable')

    @api.model
    def _face_status(self, user):
        """The account's face-recognition state for the office, or None."""
        return None
