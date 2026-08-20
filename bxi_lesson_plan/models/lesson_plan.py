from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class BxiLessonPlan(models.Model):
    _name = 'bxi.lesson.plan'
    _description = 'Lesson Plan'
    _inherit = ['mail.thread']
    _rec_name = 'topic'
    _order = 'start_date desc'

    teacher_id = fields.Many2one(
        'op.faculty', string='Teacher Name', required=True, tracking=True,
        default=lambda self: self.env['op.faculty'].search(
            [('user_id', '=', self.env.user.id)], limit=1))
    subject_id = fields.Many2one('op.subject', string='Subject', required=True, tracking=True)
    class_id = fields.Many2one('op.course', string='Class', required=True, tracking=True)
    quarter_id = fields.Many2one('op.academic.term', string='Quarter', required=True, tracking=True)
    topic = fields.Char('Topic', required=True, tracking=True)
    objective = fields.Text('Learning Objective', required=True)
    activities = fields.Text('Activities', required=True)
    resources = fields.Text('Resources', required=True)
    assessment_method = fields.Text('Assessment Method', required=True)
    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    duration = fields.Integer('Duration (Days)', compute='_compute_duration', store=True)
    plan_date = fields.Date('Date', required=True)
    plan_day = fields.Char('Day', compute='_compute_plan_day', store=True)

    line_ids = fields.One2many('bxi.lesson.plan.line', 'lesson_plan_id', string='Lines')
    recall_question_ids = fields.One2many(
        'bxi.lesson.plan.line', 'lesson_plan_id', string='Recall Questions',
        domain=[('line_type', '=', 'recall_question')])
    class_work_ids = fields.One2many(
        'bxi.lesson.plan.line', 'lesson_plan_id', string='Class Work',
        domain=[('line_type', '=', 'class_work')])
    home_work_ids = fields.One2many(
        'bxi.lesson.plan.line', 'lesson_plan_id', string='Home Work',
        domain=[('line_type', '=', 'home_work')])
    teaching_aid_ids = fields.One2many(
        'bxi.lesson.plan.line', 'lesson_plan_id', string='Teaching Aid',
        domain=[('line_type', '=', 'teaching_aid')])
    remark_ids = fields.One2many(
        'bxi.lesson.plan.line', 'lesson_plan_id', string='Remarks',
        domain=[('line_type', '=', 'remark')])

    state = fields.Selection([
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='pending', required=True, tracking=True)
    active = fields.Boolean(default=True)

    @api.depends('start_date', 'end_date')
    def _compute_duration(self):
        for plan in self:
            if plan.start_date and plan.end_date and plan.end_date >= plan.start_date:
                plan.duration = (plan.end_date - plan.start_date).days + 1
            else:
                plan.duration = 0

    @api.depends('plan_date')
    def _compute_plan_day(self):
        for plan in self:
            plan.plan_day = plan.plan_date.strftime('%A') if plan.plan_date else False

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for plan in self:
            if plan.start_date and plan.end_date and plan.start_date > plan.end_date:
                raise ValidationError(_('End Date cannot be set before Start Date.'))

    def action_resubmit(self):
        for plan in self:
            plan.state = 'pending'
            plan.message_post(body=_('Lesson plan resubmitted for review.'))
