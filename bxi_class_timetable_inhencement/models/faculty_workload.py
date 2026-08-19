from odoo import fields, models


class OpFacultyWorkload(models.Model):
    _inherit = 'op.faculty'

    max_weekly_periods = fields.Integer(default=30)
    weekly_period_count = fields.Integer(compute='_compute_weekly_period_count')
    workload_status = fields.Selection([
        ('normal', 'Normal'),
        ('near_limit', 'Near Limit'),
        ('over_limit', 'Over Limit'),
    ], compute='_compute_weekly_period_count')
    available_monday = fields.Boolean(default=True)
    available_tuesday = fields.Boolean(default=True)
    available_wednesday = fields.Boolean(default=True)
    available_thursday = fields.Boolean(default=True)
    available_friday = fields.Boolean(default=True)
    available_saturday = fields.Boolean(default=True)

    def _compute_weekly_period_count(self):
        line_model = self.env['bxi.timetable.line']
        for faculty in self:
            count = line_model.search_count([('teacher_id', '=', faculty.id)])
            faculty.weekly_period_count = count
            ratio = count / (faculty.max_weekly_periods or 1)
            if ratio > 1:
                faculty.workload_status = 'over_limit'
            elif ratio >= 0.9:
                faculty.workload_status = 'near_limit'
            else:
                faculty.workload_status = 'normal'
