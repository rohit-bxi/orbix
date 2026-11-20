# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The Help & Support screen's Contact Support and Support Hours: how to
reach the school's support desk and when it is staffed."""
from datetime import datetime

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# (label, field prefix, weekday numbers as datetime.weekday())
HOUR_SLOTS = (
    ('Monday - Friday', 'bxi_support_weekday', (0, 1, 2, 3, 4)),
    ('Saturday', 'bxi_support_saturday', (5,)),
    ('Sunday', 'bxi_support_sunday', (6,)),
)


def _hhmm(value):
    hours = int(value)
    return '%02d:%02d' % (hours, int(round((value - hours) * 60)) % 60)


class ResCompany(models.Model):
    _inherit = 'res.company'

    bxi_support_email = fields.Char('Support Email')
    bxi_support_phone = fields.Char('Support Phone')
    bxi_support_chat_enabled = fields.Boolean(
        'Live Chat', default=True,
        help='Offer "Start Chat" in the app: it opens a support ticket the desk answers.')
    # Opening hours as hours of the day (9.5 = 09:30); open == close means closed.
    bxi_support_weekday_open = fields.Float('Mon-Fri Opens', default=9.0)
    bxi_support_weekday_close = fields.Float('Mon-Fri Closes', default=18.0)
    bxi_support_saturday_open = fields.Float('Saturday Opens', default=10.0)
    bxi_support_saturday_close = fields.Float('Saturday Closes', default=16.0)
    bxi_support_sunday_open = fields.Float('Sunday Opens', default=0.0)
    bxi_support_sunday_close = fields.Float('Sunday Closes', default=0.0)

    @api.constrains(*[f'{prefix}_{end}' for _label, prefix, _days in HOUR_SLOTS for end in ('open', 'close')])
    def _check_bxi_support_hours(self):
        for company in self:
            for label, prefix, _days in HOUR_SLOTS:
                opens, closes = company[f'{prefix}_open'], company[f'{prefix}_close']
                if not (0 <= opens <= 24 and 0 <= closes <= 24) or closes < opens:
                    raise ValidationError(_('Support hours for %s must be between 00:00 and 24:00, '
                                            'closing after opening.', label))

    def _bxi_support_hours(self, now=None):
        """([{days, opens, closes, closed}], currently_open) in the school's
        time zone."""
        self.ensure_one()
        tz = pytz.timezone(self.resource_calendar_id.tz or 'UTC')
        local = (now or datetime.utcnow()).replace(tzinfo=pytz.utc).astimezone(tz)
        hour = local.hour + local.minute / 60.0
        rows, currently_open = [], False
        for label, prefix, days in HOUR_SLOTS:
            opens, closes = self[f'{prefix}_open'], self[f'{prefix}_close']
            closed = opens == closes
            rows.append({'days': label, 'opens': None if closed else _hhmm(opens),
                         'closes': None if closed else _hhmm(closes), 'closed': closed})
            if local.weekday() in days and not closed and opens <= hour < closes:
                currently_open = True
        return rows, currently_open
