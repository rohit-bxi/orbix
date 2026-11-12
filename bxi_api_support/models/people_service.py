# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Account & Security for the office's teacher / student / parent screens:
creating a person's login, one-time passwords, sending credentials and the
face-recognition hook (implemented by bxi_face_auth)."""
import logging

from markupsafe import Markup, escape

from odoo import _, api, models

from odoo.addons.bxi_api.controllers.auth import api_error

_logger = logging.getLogger(__name__)

ROLE_MODELS = {'teacher': 'op.faculty', 'student': 'op.student', 'parent': 'op.parent'}
CREDENTIAL_CHANNELS = ('email', 'sms')


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

    # -- credentials ----------------------------------------------------------------

    @api.model
    def _send_credentials(self, record, user, password, channel):
        """Send `user`'s username and one-time password. Never raises: a
        send that failed comes back as {'sent': False, 'reason': ...}."""
        if channel == 'sms':
            phone = self._phone(record)
            if not phone:
                return {'channel': channel, 'sent': False, 'reason': 'no_phone'}
            sent = self.env['bxi.msg91.client'].sudo().send_credentials_sms(phone, user.login, password)
            return {'channel': channel, 'sent': sent, 'reason': None if sent else 'sms_not_sent'}
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
            'email_from': company.email_formatted or self.env['ir.mail_server']._get_default_from_address()
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
