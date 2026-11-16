# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import api, models
from odoo.exceptions import AccessDenied
from odoo.tools.misc import hmac
from odoo.tools.translate import LazyTranslate

from odoo.addons.bxi_identity_verification.models.aadhaar import normalize_aadhaar

from .res_company import ROLE_BY_MODEL

_lt = LazyTranslate(__name__)

# Credential type for res.users.authenticate / session.authenticate: an
# emailed one-time code (bxi.otp.request, channel 'email', purpose 'login').
EMAIL_OTP_CREDENTIAL = 'bxi_email_otp'

OTP_FAILURE_MESSAGES = {
    'not_found': _lt('No login code was requested, or it was already used. Request a new code.'),
    'expired': _lt('This code has expired. Request a new code.'),
    'too_many_attempts': _lt('Too many wrong codes. Request a new code.'),
    'invalid_code': _lt('The code is not correct.'),
}


class EmailOtpDenied(AccessDenied):
    """A refused emailed code; `reason` is one of OTP_FAILURE_MESSAGES."""

    def __init__(self, reason):
        self.reason = reason if reason in OTP_FAILURE_MESSAGES else 'invalid_code'
        super().__init__(str(OTP_FAILURE_MESSAGES[self.reason]))


def mask_email(email):
    """'vijay@gmail.com' -> 'v***@g***.com'."""
    local, _sep, domain = (email or '').strip().partition('@')
    if not local or not domain:
        return None
    name, _dot, tld = domain.rpartition('.')
    if not name:
        name, tld = domain, ''
    return '%s***@%s***%s' % (local[0], name[0], '.' + tld if tld else '')


class ResUsers(models.Model):
    _inherit = 'res.users'

    # -- finding the account behind an Aadhaar number ----------------------------------

    @api.model
    def _bxi_aadhaar_record_eligible(self, record):
        """True when `record` (a student/teacher/parent) may sign in to its
        login by Aadhaar under its school's settings."""
        record = record.sudo()
        if 'active' in record._fields and not record.active:
            return False
        user = record.user_id
        if not user or not user.active:
            return False
        company = user.company_id
        if not company.bxi_aadhaar_login_enabled or not company._bxi_aadhaar_role_allowed(ROLE_BY_MODEL[record._name]):
            return False
        status = record.aadhar_verification_status
        if status == 'rejected':
            return False
        if company.bxi_aadhaar_login_requires_verified and status != 'verified':
            return False
        return True

    @api.model
    def _bxi_aadhaar_resolve(self, number):
        """(user, records, reason) for an Aadhaar number as typed.
        `records` are the matching student/teacher/parent records of that
        login. `reason` is None on success, else 'invalid' (not an Aadhaar
        number), 'not_found' (no login may use it) or 'ambiguous' (it
        leads to more than one login - old data the office must fix)."""
        digits = normalize_aadhaar(number)
        if not digits:
            return self.browse(), [], 'invalid'
        holders = self.env['bxi.identity.verification.mixin']._bxi_aadhaar_holders(digits)
        eligible = [record for record in holders if self._bxi_aadhaar_record_eligible(record)]
        users = self.browse()
        for record in eligible:
            users |= record.sudo().user_id
        if not users:
            return users, [], 'not_found'
        if len(users) > 1:
            return self.browse(), [], 'ambiguous'
        return users.sudo(), eligible, None

    def _bxi_aadhaar_login_records(self):
        """This login's student/teacher/parent records that can be used for
        Aadhaar login right now."""
        self.ensure_one()
        records = []
        for model in ROLE_BY_MODEL:
            records.extend(self.env[model].sudo().search(
                [('user_id', '=', self.id), ('bxi_aadhaar_last4', '!=', False)]))
        return [record for record in records if self._bxi_aadhaar_record_eligible(record)]

    # -- where an emailed code goes ---------------------------------------------------

    @api.model
    def _bxi_record_email(self, record):
        """The email address on a student/teacher/parent record."""
        record = record.sudo()
        if record._name == 'op.parent':
            return record.email or record.name.email or False
        return record.email or False

    def _bxi_aadhaar_otp_email(self, records):
        """Where the login code for this account goes: the email on the
        matching record, else the account's own email; for a student
        without either, a linked parent's email (most students are minors)."""
        self.ensure_one()
        for record in records:
            email = self._bxi_record_email(record)
            if email:
                return email
        if self.email:
            return self.email
        for record in records:
            if record._name == 'op.student' and 'parent_ids' in record._fields:
                for parent in record.sudo().parent_ids:
                    email = self._bxi_record_email(parent)
                    if email:
                        return email
        return False

    @api.model
    def _bxi_fake_email_hint(self, number):
        """A stable, made-up hint for a number no account may use, so the
        code-request reply looks the same either way."""
        digest = hmac(self.env(su=True), 'bxi-aadhaar-fake-hint', normalize_aadhaar(number) or number or '')
        letters = 'abcdefghijklmnoprstuvy'
        domains = ('g', 'g', 'y', 'o', 'r', 'h')
        return '%s***@%s***.com' % (letters[int(digest[:4], 16) % len(letters)],
                                    domains[int(digest[4:8], 16) % len(domains)])

    # -- authentication ------------------------------------------------------------------

    def _check_credentials(self, credential, env):
        """Credential {'type': 'bxi_email_otp', 'login', 'otp'}: an emailed
        login code (see the Aadhaar login routes). Going through
        authenticate() keeps Odoo's failed-login cooldown and logging,
        which only ever see the real username."""
        if credential.get('type') == EMAIL_OTP_CREDENTIAL:
            user = self.env.user
            ok, reason = self.env['bxi.otp.request'].sudo()._verify_for_user(
                user, (credential.get('otp') or '').strip(), purpose='login')
            if not ok:
                raise EmailOtpDenied(reason)
            return {'uid': user.id, 'auth_method': EMAIL_OTP_CREDENTIAL, 'mfa': 'default'}
        return super()._check_credentials(credential, env)

    # -- profile -----------------------------------------------------------------------

    def _get_bxi_api_profile(self):
        profile = super()._get_bxi_api_profile()
        records = self._bxi_aadhaar_login_records()
        profile['aadhaar_login'] = {
            'available': bool(records),
            'last4': records[0].bxi_aadhaar_last4 if records else None,
        }
        return profile
