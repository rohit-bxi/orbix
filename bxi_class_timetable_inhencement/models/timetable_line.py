from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class BxiTimetableLine(models.Model):
    _name = 'bxi.timetable.line'
    _description = 'Timetable Period'
    _order = 'day, timing_id'

    timetable_id = fields.Many2one('bxi.timetable', required=True, ondelete='cascade')
    day = fields.Selection([
        ('monday', 'Monday'), ('tuesday', 'Tuesday'), ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'), ('friday', 'Friday'), ('saturday', 'Saturday'),
    ], required=True)
    timing_id = fields.Many2one('op.timing', string='Period', required=True,
                                 domain=[('is_break', '=', False)])
    subject_id = fields.Many2one('op.subject', string='Subject')
    teacher_id = fields.Many2one('op.faculty', string='Teacher')

    _unique_slot = models.Constraint(
        'unique(timetable_id, day, timing_id)',
        'A period is already scheduled for this Class/Section on this Day and Time Slot.',
    )

    @api.constrains('timetable_id')
    def _check_not_locked(self):
        for line in self:
            if line.timetable_id.locked:
                raise ValidationError(_('This timetable is locked. Unlock it before making changes.'))

    @staticmethod
    def _timing_range(timing):
        """(start, end) in minutes-since-midnight for an op.timing period, so
        overlap can be checked by range rather than by exact record match -
        two different op.timing records can still represent overlapping
        wall-clock ranges (e.g. after a bell-schedule edit)."""
        hour = int(timing.hour or 0) % 12
        if timing.am_pm == 'pm':
            hour += 12
        start = hour * 60 + int(timing.minute or 0)
        end = start + int((timing.duration or 0) * 60)
        return start, end

    @api.constrains('teacher_id', 'day', 'timing_id')
    def _check_teacher_not_double_booked(self):
        for line in self.filtered('teacher_id'):
            start, end = self._timing_range(line.timing_id)
            candidates = self.search([
                ('id', '!=', line.id),
                ('teacher_id', '=', line.teacher_id.id),
                ('day', '=', line.day),
            ])
            for clash in candidates:
                other_start, other_end = self._timing_range(clash.timing_id)
                if start < other_end and other_start < end:
                    raise ValidationError(_(
                        '%(teacher)s is already scheduled for %(class_name)s at this time.',
                        teacher=line.teacher_id.name, class_name=clash.timetable_id.display_name))

    def unlink(self):
        for line in self:
            if line.timetable_id.locked:
                raise ValidationError(_('This timetable is locked. Unlock it before making changes.'))
        return super().unlink()

    def action_open_remove_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'bxi.remove.period.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_line_id': self.id},
        }
