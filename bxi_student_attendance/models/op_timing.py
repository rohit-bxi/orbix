from datetime import datetime, time, timedelta

import pytz

from odoo import models


class OpTiming(models.Model):
    _inherit = 'op.timing'

    def _to_datetime(self, target_date):
        """Return (start, end) as naive UTC datetimes for this Period on
        `target_date`, for the current company's timezone.

        Mirrors, in reverse, the local-time formatting `op.session`
        already does for display (see `_compute_timing` in
        openeducat_timetable), so a session generated here shows the
        same period time a user would expect.
        """
        self.ensure_one()
        hour = int(self.hour) % 12
        if self.am_pm == 'pm':
            hour += 12
        minute = int(self.minute)
        tz = pytz.timezone(self.env.company.partner_id.tz or 'UTC')
        local_start = tz.localize(datetime.combine(target_date, time(hour=hour, minute=minute)))
        start = local_start.astimezone(pytz.utc).replace(tzinfo=None)
        duration_minutes = int(round((self.duration or 1.0) * 60))
        end = start + timedelta(minutes=duration_minutes)
        return start, end
