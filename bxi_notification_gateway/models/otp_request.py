# -*- coding: utf-8 -*-

import hashlib
import secrets
from datetime import timedelta

from odoo import api, fields, models

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5


class BxiOtpRequest(models.Model):
    """A one-time code issued for a phone number. The code is generated and
    checked entirely in Odoo - the SMS provider (bxi.msg91.client) is only
    used to deliver it, so verification never depends on a third party
    being reachable.
    """
    _name = 'bxi.otp.request'
    _description = 'Orbix OTP Request'
    _order = 'create_date desc'

    phone = fields.Char(required=True, index=True)
    purpose = fields.Selection([('login', 'Login')], required=True, default='login')
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
