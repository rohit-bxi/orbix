from odoo import _, fields, models
from odoo.exceptions import ValidationError

DAY_SELECTION = [
    ('monday', 'Monday'), ('tuesday', 'Tuesday'), ('wednesday', 'Wednesday'),
    ('thursday', 'Thursday'), ('friday', 'Friday'), ('saturday', 'Saturday'),
]


class BxiTransferPeriodWizard(models.TransientModel):
    _name = 'bxi.transfer.period.wizard'
    _description = 'Transfer Teaching Period'

    from_teacher_id = fields.Many2one('op.faculty', string='From Teacher', required=True)
    course_id = fields.Many2one('op.course', string='Class', required=True)
    batch_id = fields.Many2one('op.batch', string='Section', required=True,
                                domain="[('course_id', '=', course_id)]")
    day = fields.Selection(DAY_SELECTION, required=True)
    timing_id = fields.Many2one('op.timing', string='Time Period', required=True,
                                 domain=[('is_break', '=', False)])
    to_teacher_id = fields.Many2one('op.faculty', string='Transfer To', required=True)

    def action_transfer(self):
        self.ensure_one()
        timetable = self.env['bxi.timetable']._get_or_create(self.course_id.id, self.batch_id.id)
        line = self.env['bxi.timetable.line'].search([
            ('timetable_id', '=', timetable.id),
            ('day', '=', self.day),
            ('timing_id', '=', self.timing_id.id),
            ('teacher_id', '=', self.from_teacher_id.id),
        ], limit=1)
        if not line:
            raise ValidationError(_('No matching period found for this teacher, class and time slot.'))
        if line.timetable_id.locked:
            raise ValidationError(_('This timetable is locked. Unlock it before making changes.'))
        if not self.env.context.get('force_workload_override') and \
                self.to_teacher_id.weekly_period_count + 1 > self.to_teacher_id.max_weekly_periods:
            raise ValidationError(_(
                '%(teacher)s is already at their weekly period limit (%(count)s/%(max)s).',
                teacher=self.to_teacher_id.name, count=self.to_teacher_id.weekly_period_count,
                max=self.to_teacher_id.max_weekly_periods))
        line.teacher_id = self.to_teacher_id.id
