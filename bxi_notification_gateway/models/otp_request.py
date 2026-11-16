# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

import hashlib
import logging
import secrets
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
# Emailed codes: at most one per minute and EMAIL_MAX_PER_HOUR per hour
# for an account, so the route can't be used to flood someone's inbox.
EMAIL_RESEND_SECONDS = 60
EMAIL_MAX_PER_HOUR = 5


class BxiOtpRequest(models.Model):
    """A one-time code issued for a phone number (sent by SMS) or for an
    account (sent by email, `channel` 'email'). The code is generated and
    checked entirely in Odoo - the SMS provider (bxi.msg91.client) or the
    mail server is only used to deliver it, so verification never depends
    on a third party being reachable. Only a hash of the code is stored.
    """
    _name = 'bxi.otp.request'
    _description = 'Orbix OTP Request'
    _order = 'create_date desc'

    channel = fields.Selection([('sms', 'SMS'), ('email', 'Email')], required=True, default='sms')
    phone = fields.Char(index=True)
    user_id = fields.Many2one('res.users', string='Account', index=True, ondelete='cascade',
                              help='Emailed codes: the account the code signs in to.')
    email = fields.Char(help='Emailed codes: where the code was sent.')
    purpose = fields.Selection([
        ('login', 'Login'),
        ('password_reset', 'Password Reset'),
        ('step_up', 'Confirm Sensitive Action'),
    ], required=True, default='login')
    code_hash = fields.Char(required=True)
    expires_at = fields.Datetime(required=True)
    verified_at = fields.Datetime(readonly=True)
    attempts = fields.Integer(default=0)

    @staticmethod
    def _hash(code):
        return hashlib.sha256(code.encode()).hexdigest()

    @api.model
    def _generate_and_send(self, phone, purpose='login'):
        """Create a fresh OTP for `phone` and send it via MSG91. Returns
        True if the SMS was handed off successfully, False otherwise (the
        OTP record is created either way, so a retry can reuse it until it
        expires rather than spamming new codes).
        """
        code = f'{secrets.randbelow(1000000):06d}'
        self.sudo().create({
            'phone': phone,
            'purpose': purpose,
            'code_hash': self._hash(code),
            'expires_at': fields.Datetime.now() + timedelta(minutes=OTP_TTL_MINUTES),
        })
        return self.env['bxi.msg91.client'].sudo().send_otp_sms(phone, code)

    @api.model
    def _verify(self, phone, code, purpose='login'):
        """Returns (ok: bool, reason: str|None). `reason` is one of
        'not_found', 'expired', 'too_many_attempts', 'invalid_code' when
        ok is False.
        """
        otp = self.sudo().search([
            ('phone', '=', phone),
            ('purpose', '=', purpose),
            ('verified_at', '=', False),
        ], order='create_date desc', limit=1)
        if not otp:
            return False, 'not_found'
        if otp.expires_at < fields.Datetime.now():
            return False, 'expired'
        if otp.attempts >= OTP_MAX_ATTEMPTS:
            return False, 'too_many_attempts'

        otp.attempts += 1
        if otp.code_hash != self._hash(code):
            return False, 'invalid_code'

        otp.verified_at = fields.Datetime.now()
        return True, None

    # -- emailed codes -----------------------------------------------------------------

    @api.model
    def _email_throttled(self, user):
        """True when `user` was emailed a code too recently / too often."""
        now = fields.Datetime.now()
        recent = self.sudo().search([
            ('channel', '=', 'email'), ('user_id', '=', user.id),
            ('create_date', '>=', now - timedelta(hours=1)),
        ], order='create_date desc')
        if len(recent) >= EMAIL_MAX_PER_HOUR:
            return True
        return bool(recent) and recent[0].create_date > now - timedelta(seconds=EMAIL_RESEND_SECONDS)

    @api.model
    def _generate_and_email(self, user, email, purpose='login'):
        """Email a fresh code for `user` to `email`. Returns 'sent',
        'throttled' (nothing sent, the last code is still the one to use)
        or 'failed' (the mail server refused it; the code still works)."""
        if self._email_throttled(user):
            return 'throttled'
        code = f'{secrets.randbelow(1000000):06d}'
        self.sudo().create({
            'channel': 'email',
            'user_id': user.id,
            'email': email,
            'purpose': purpose,
            'code_hash': self._hash(code),
            'expires_at': fields.Datetime.now() + timedelta(minutes=OTP_TTL_MINUTES),
        })
        return 'sent' if self._send_otp_email(user, email, code) else 'failed'

    @api.model
    def _send_otp_email(self, user, email, code):
        """Send `code` now with the 'Orbix: Login Code' email template.
        The mail record is deleted afterwards, sent or not, so the code is
        never kept in the outgoing mail queue. Returns True when sent."""
        template = self.env.ref('bxi_notification_gateway.mail_template_otp_email', raise_if_not_found=False)
        if not template:
            _logger.warning('Login code email template is missing; code not sent.')
            return False
        company = user.company_id or self.env.company
        email_from = (company.email_formatted or self.env['ir.mail_server'].sudo()._get_default_from_address()
                      or False)
        mail_id = template.sudo().with_context(
            otp_code=code, otp_minutes=OTP_TTL_MINUTES, lang=user.lang,
        ).send_mail(user.id, email_values={
            'email_to': email, 'email_from': email_from, 'auto_delete': True,
        })
        mail = self.env['mail.mail'].sudo().browse(mail_id)
        try:
            mail.send(raise_exception=False)
        except Exception:  # noqa: BLE001 - a mail server problem must not break the login route
            _logger.exception('Sending a login code email (user %s) failed.', user.id)
        sent = not mail.exists() or mail.state == 'sent'
        if not sent:
            _logger.warning('Login code email for user %s not sent: %s', user.id,
                            mail.failure_reason or mail.state)
        if mail.exists():
            mail.unlink()
        return sent

    @api.model
    def _verify_for_user(self, user, code, purpose='login'):
        """Check an emailed code for `user`; same results as _verify."""
        otp = self.sudo().search([
            ('channel', '=', 'email'),
            ('user_id', '=', user.id),
            ('purpose', '=', purpose),
            ('verified_at', '=', False),
        ], order='create_date desc, id desc', limit=1)
        if not otp:
            return False, 'not_found'
        if otp.expires_at < fields.Datetime.now():
            return False, 'expired'
        if otp.attempts >= OTP_MAX_ATTEMPTS:
            return False, 'too_many_attempts'

        otp.attempts += 1
        if otp.code_hash != self._hash(code or ''):
            return False, 'invalid_code'

        otp.verified_at = fields.Datetime.now()
        return True, None
