# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import re

from odoo import api, models
from odoo.tools import SQL


def normalize_phone(phone):
    """Digits only, compared on the last 10 when both sides have that many,
    so '+91 98765-43210', '09876543210' and '9876543210' all match."""
    digits = re.sub(r'\D', '', phone or '')
    return digits[-10:] if len(digits) >= 10 else digits


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _bxi_find_users_by_phone(self, phone):
        """Active users whose phone matches `phone` - used by OTP login and
        OTP password reset. bxi_api_support extends this to also match
        op.parent.mobile. More than one result means the number is shared
        and the caller must refuse rather than guess.
        """
        partner_ids = self._bxi_partner_ids_with_phone('res_partner', 'phone', phone)
        return self.sudo().search([('partner_id', 'in', partner_ids)])

    def _bxi_get_otp_phone(self):
        """The number an OTP for this account (password reset by login) is
        texted to; extended alongside _bxi_find_users_by_phone."""
        self.ensure_one()
        return self.phone

    @api.model
    def _bxi_partner_ids_with_phone(self, table, column, phone):
        """Ids of `table` rows whose `column` is the same number as `phone`
        once separators/country prefix are ignored (see normalize_phone).
        Done in SQL so numbers stored as '98765-43210' still match."""
        wanted = normalize_phone(phone)
        if len(wanted) < 6:
            return []
        rows = self.env.execute_query(SQL(
            "SELECT id FROM %s WHERE %s IS NOT NULL AND RIGHT(REGEXP_REPLACE(%s, '\\D', '', 'g'), 10) = %s",
            SQL.identifier(table), SQL.identifier(column), SQL.identifier(column), wanted,
        ))
        return [row[0] for row in rows]
