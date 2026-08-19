from odoo import _, fields, models
from odoo.exceptions import ValidationError

DAY_SELECTION = [
    ('monday', 'Monday'), ('tuesday', 'Tuesday'), ('wednesday', 'Wednesday'),
    ('thursday', 'Thursday'), ('friday', 'Friday'), ('saturday', 'Saturday'),
]


class BxiAddPeriodWizard(models.TransientModel):
    _name = 'bxi.add.period.wizard'
    _description = 'Add Teaching Period'

    teacher_id = fields.Many2one('op.faculty', required=True)
    course_id = fields.Many2one('op.course', string='Class', required=True)
    batch_id = fields.Many2one('op.batch', string='Section', required=True,
                                domain="[('course_id', '=', course_id)]")
    day = fields.Selection(DAY_SELECTION, required=True)
    timing_id = fields.Many2one('op.timing', string='Time Period', required=True,
                                 domain=[('is_break', '=', False)])
    subject_id = fields.Many2one('op.subject', string='Subject', required=True)

    def action_add_period(self):
        self.ensure_one()
        timetable = self.env['bxi.timetable']._get_or_create(self.course_id.id, self.batch_id.id)
        if timetable.locked:
            raise ValidationError(_('This timetable is locked. Unlock it before making changes.'))
        if not self.env.context.get('force_workload_override') and \
                self.teacher_id.weekly_period_count + 1 > self.teacher_id.max_weekly_periods:
            raise ValidationError(_(
                '%(teacher)s is already at their weekly period limit (%(count)s/%(max)s).',
                teacher=self.teacher_id.name, count=self.teacher_id.weekly_period_count,
                max=self.teacher_id.max_weekly_periods))
        self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id,
            'day': self.day,
            'timing_id': self.timing_id.id,
            'subject_id': self.subject_id.id,
            'teacher_id': self.teacher_id.id,
        })
