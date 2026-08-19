from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


def _float_to_hm(value):
    hours = int(value)
    minutes = int(round((value - hours) * 60))
    return '%d:%02d' % (hours, minutes)


class OpTimingClassTimetable(models.Model):
    _inherit = 'op.timing'

    start_time = fields.Float('Start Time')
    end_time = fields.Float('End Time')
    is_break = fields.Boolean('Is Break', default=False)
    display_label = fields.Char(compute='_compute_display_label', store=True)

    @api.depends('name', 'start_time', 'end_time', 'is_break')
    def _compute_display_label(self):
        for timing in self:
            time_range = '%s - %s' % (_float_to_hm(timing.start_time), _float_to_hm(timing.end_time))
            if timing.is_break:
                timing.display_label = 'Break (%s)' % time_range
            else:
                timing.display_label = '%s (%s)' % (timing.name, time_range)

    @api.constrains('start_time', 'end_time')
    def _check_time_range(self):
        for timing in self:
            if timing.end_time and timing.end_time <= timing.start_time:
                raise ValidationError(_('End Time must be after Start Time.'))
