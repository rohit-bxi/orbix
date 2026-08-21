from datetime import datetime, timedelta

from odoo import fields, models


class BxiPtmMeeting(models.Model):
    _inherit = 'bxi.ptm.meeting'

    event_id = fields.Many2one('event.event', readonly=True, copy=False)

    def action_convert_to_event(self):
        """Create an event.event (category 'ptm') mirroring this meeting.

        Left as an explicit, per-record admin action rather than an automatic
        migration on install: this touches another module's existing data and
        should be a deliberate choice, not a silent side effect of installing
        this module.
        """
        Event = self.env['event.event']
        for meeting in self.filtered(lambda m: not m.event_id):
            start = datetime.combine(meeting.date, datetime.min.time()) + timedelta(hours=meeting.time)
            meeting.event_id = Event.create({
                'name': meeting.name,
                'event_category': 'ptm',
                'date_begin': start,
                'date_end': start + timedelta(hours=1),
                'target_audience': 'specific_class',
                'course_ids': [(6, 0, meeting.class_ids.ids)],
                'note': meeting.venue and f'Venue: {meeting.venue}' or False,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Events',
            'res_model': 'event.event',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.mapped('event_id').ids)],
        }
