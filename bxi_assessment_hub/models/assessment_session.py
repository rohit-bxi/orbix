# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import _, api, fields, models


class BxiAssessmentSession(models.Model):
    _name = 'bxi.assessment.session'
    _description = 'Assigned Assessment Session'
    _inherit = ['mail.thread']
    _order = 'exam_date desc, exam_time desc'

    exam_id = fields.Many2one(
        'bxi.exam', string='Exam', required=True, tracking=True,
        domain=[('state', '=', 'published')])
    class_id = fields.Many2one('op.course', string='Class', required=True, tracking=True)
    teacher_id = fields.Many2one(
        'op.faculty', string='Teacher', required=True, tracking=True,
        default=lambda self: self.env['op.faculty'].search(
            [('user_id', '=', self.env.user.id)], limit=1))
    exam_date = fields.Date(string='Exam Date', required=True, default=fields.Date.context_today, tracking=True)
    exam_time = fields.Float(string='Exam Time', required=True, default=9.0)
    total_marks = fields.Float(related='exam_id.total_marks', string='Total Marks', readonly=True)
    student_ids = fields.Many2many('op.student', string='Students', required=True)
    state = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], default='scheduled', required=True, tracking=True)
    submission_ids = fields.One2many('bxi.assessment.submission', 'session_id', string='Submissions')
    submission_count = fields.Integer(compute='_compute_submission_count')
    assignment_summary = fields.Char(compute='_compute_assignment_summary', string='Summary')

    @api.depends('submission_ids')
    def _compute_submission_count(self):
        for session in self:
            session.submission_count = len(session.submission_ids)

    @api.depends('exam_id.question_count', 'exam_id.total_marks', 'student_ids')
    def _compute_assignment_summary(self):
        for session in self:
            session.assignment_summary = _(
                '%(questions)d question(s) - %(marks)s total marks - %(students)d student(s) selected'
            ) % {
                'questions': session.exam_id.question_count,
                'marks': session.exam_id.total_marks,
                'students': len(session.student_ids),
            }

    @api.onchange('exam_id')
    def _onchange_exam_id(self):
        if self.exam_id and not self.class_id:
            self.class_id = self.exam_id.class_id
        if self.exam_id and not self.teacher_id:
            self.teacher_id = self.exam_id.teacher_id

    @api.onchange('class_id')
    def _onchange_class_id(self):
        if self.class_id:
            details = self.env['op.student.course'].search([
                ('course_id', '=', self.class_id.id), ('state', '=', 'running'),
            ])
            self.student_ids = details.mapped('student_id')

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    @api.model_create_multi
    def create(self, vals_list):
        sessions = super().create(vals_list)
        for session in sessions:
            session._create_submissions()
        return sessions

    def _create_submissions(self):
        self.ensure_one()
        Submission = self.env['bxi.assessment.submission']
        Answer = self.env['bxi.assessment.submission.answer']
        existing_students = self.submission_ids.mapped('student_id')
        for student in self.student_ids - existing_students:
            submission = Submission.create({
                'session_id': self.id,
                'student_id': student.id,
            })
            for question in self.exam_id.question_ids:
                Answer.create({
                    'submission_id': submission.id,
                    'question_id': question.id,
                })
