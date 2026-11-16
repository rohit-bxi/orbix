# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""19.0.1.3.0: Aadhaar numbers become look-up-able (bxi_aadhaar_hash).

- Store existing numbers as plain 12 digits (spaces/dashes removed).
- A number with status 'unverified' was typed by the school office (the
  family's own submission sets 'pending'), and office-entered numbers now
  count as verified - so mark those verified.
- (Re)compute the hash and last 4 digits.
- Log invalid numbers and numbers shared by different people, by record
  id only - never the number. Nothing is changed for them: an invalid
  number gets no hash, and a shared one is refused at login until the
  office fixes it.
"""
import logging

from odoo import SUPERUSER_ID, api, fields

from odoo.addons.bxi_identity_verification.models.aadhaar import clean_aadhaar, is_valid_aadhaar
from odoo.addons.bxi_identity_verification.models.identity_verification_mixin import AADHAAR_MODELS

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False})
    now = fields.Datetime.now()
    by_hash = {}
    for model_name in AADHAAR_MODELS:
        Model = env[model_name]
        table = Model._table
        cr.execute(f"SELECT id, aadhar_card, aadhar_verification_status FROM {table} "
                   f"WHERE aadhar_card IS NOT NULL AND aadhar_card != ''")
        rows = cr.fetchall()
        invalid = []
        for record_id, value, status in rows:
            cleaned = clean_aadhaar(value)
            if cleaned != value:
                cr.execute(f"UPDATE {table} SET aadhar_card = %s WHERE id = %s", [cleaned or None, record_id])
            if not is_valid_aadhaar(cleaned):
                invalid.append(record_id)
            elif (status or 'unverified') == 'unverified':
                cr.execute(f"UPDATE {table} SET aadhar_verification_status = 'verified', "
                           f"aadhar_verified_at = %s WHERE id = %s", [now, record_id])
        records = Model.browse([row[0] for row in rows])
        records.invalidate_recordset()
        env.add_to_compute(Model._fields['bxi_aadhaar_hash'], records)
        env.add_to_compute(Model._fields['bxi_aadhaar_last4'], records)
        records.flush_recordset()
        for record in records:
            if record.bxi_aadhaar_hash:
                by_hash.setdefault(record.bxi_aadhaar_hash, []).append(record)
        if invalid:
            _logger.warning('Aadhaar: %s %s record(s) hold an invalid number and cannot be used to log in: ids %s',
                            len(invalid), model_name, invalid)
    for holders in by_hash.values():
        first = holders[0]
        others = [holder for holder in holders[1:] if not first._bxi_same_person(holder)]
        if others:
            _logger.warning('Aadhaar: one number is shared by different people: %s',
                            ', '.join(f'{holder._name}({holder.id})' for holder in [first] + others))
