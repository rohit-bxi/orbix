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

    @api.constrains('teacher_id', 'day', 'timing_id')
    def _check_teacher_not_double_booked(self):
        for line in self.filtered('teacher_id'):
            clash = self.search([
                ('id', '!=', line.id),
                ('teacher_id', '=', line.teacher_id.id),
                ('day', '=', line.day),
                ('timing_id', '=', line.timing_id.id),
            ], limit=1)
            if clash:
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
