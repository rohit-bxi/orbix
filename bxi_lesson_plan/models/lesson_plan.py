# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
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
    duration_label = fields.Char(
        'Duration', tracking=True,
        help='As the teacher puts it on the Create Lesson Plan screen, e.g. "5 days" or "2 weeks". '
             'Duration (Days) is counted from the start and end dates.')
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

    @api.constrains('start_date', 'end_date', 'plan_date')
    def _check_dates(self):
        for plan in self:
            if plan.start_date and plan.end_date and plan.start_date > plan.end_date:
                raise ValidationError(_('End Date cannot be set before Start Date.'))
            if plan.plan_date and plan.start_date and plan.end_date \
                    and not plan.start_date <= plan.plan_date <= plan.end_date:
                raise ValidationError(_('The Day and Date must be between the Start Date and the End Date.'))

    @api.model
    def _bxi_quarter_for(self, day):
        """The academic term (quarter) a plan starting on `day` belongs to:
        the narrowest term covering that day, so a quarter wins over the
        half-year it sits in."""
        if not day:
            return self.env['op.academic.term']
        terms = self.env['op.academic.term'].sudo().search([
            ('term_start_date', '<=', day), ('term_end_date', '>=', day)])
        return terms.sorted(lambda t: ((t.term_end_date - t.term_start_date).days, -t.id))[:1]

    @api.onchange('start_date')
    def _onchange_start_date_quarter(self):
        quarter = self._bxi_quarter_for(self.start_date)
        if quarter and (not self.quarter_id or self.start_date and not (
                self.quarter_id.term_start_date <= self.start_date <= self.quarter_id.term_end_date)):
            self.quarter_id = quarter

    @api.model_create_multi
    def create(self, vals_list):
        # The Create Lesson Plan screen has no Quarter: take it from the dates.
        for vals in vals_list:
            if not vals.get('quarter_id') and vals.get('start_date'):
                quarter = self._bxi_quarter_for(fields.Date.to_date(vals['start_date']))
                if quarter:
                    vals['quarter_id'] = quarter.id
        return super().create(vals_list)

    def action_resubmit(self):
        for plan in self:
            plan.state = 'pending'
            plan.message_post(body=_('Lesson plan resubmitted for review.'))
