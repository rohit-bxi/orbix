# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Aadhaar number helpers: clean-up, format + checksum check, keyed hash
and masking. Used by the identity mixin, the people API and Aadhaar login
(bxi_aadhaar_login).

The number is only ever *looked up* through its keyed hash
(`bxi_aadhaar_hash`): an HMAC with the database secret, so the index holds
nothing that can be reversed without that secret.
"""
import re

from odoo.exceptions import ValidationError
from odoo.tools.misc import hmac

HASH_SCOPE = 'bxi-aadhaar-number'
AADHAAR_LENGTH = 12
# Separators people type between the digit groups.
_SEPARATORS = re.compile(r'[\s\-.]')

# Verhoeff checksum tables (the last Aadhaar digit is a Verhoeff check digit).
_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


class AadhaarInUseError(ValidationError):
    """The number already belongs to a different person."""


def clean_aadhaar(value):
    """`value` without spaces/dashes/dots, or '' for an empty value. The
    result is not necessarily valid - see is_valid_aadhaar."""
    if not value or not isinstance(value, str):
        return ''
    return _SEPARATORS.sub('', value)


def verhoeff_check_digit(digits):
    """The Verhoeff check digit to append to the string of digits `digits`."""
    check = 0
    for index, digit in enumerate(reversed(digits)):
        check = _D[check][_P[(index + 1) % 8][int(digit)]]
    return str(_INV[check])


def is_valid_aadhaar(digits):
    """True for 12 digits, not starting with 0 or 1, with a valid Verhoeff
    check digit. `digits` must already be cleaned."""
    if not digits or len(digits) != AADHAAR_LENGTH or not digits.isdigit() or digits[0] in '01':
        return False
    check = 0
    for index, digit in enumerate(reversed(digits)):
        check = _D[check][_P[index % 8][int(digit)]]
    return check == 0


def normalize_aadhaar(value):
    """The 12 digits of a valid Aadhaar number typed in any common format,
    or None when `value` is not a valid Aadhaar number."""
    digits = clean_aadhaar(value)
    return digits if is_valid_aadhaar(digits) else None


def looks_like_aadhaar(value):
    """True when `value` is typed like an Aadhaar number (digits and
    separators only) and is a valid one."""
    if not value or not isinstance(value, str) or not re.fullmatch(r'[\d\s\-.]+', value.strip()):
        return False
    return normalize_aadhaar(value.strip()) is not None


def aadhaar_hash(env, digits):
    """Keyed hash of a normalized Aadhaar number (see module docstring)."""
    return hmac(env(su=True), HASH_SCOPE, digits)


def mask_aadhaar(last4):
    return 'XXXX XXXX %s' % last4 if last4 else None


def check_aadhaar_or_raise(value, message):
    """The normalized number, or a ValidationError with `message`."""
    digits = normalize_aadhaar(value)
    if not digits:
        raise ValidationError(message)
    return digits
