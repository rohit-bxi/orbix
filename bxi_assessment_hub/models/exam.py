# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BxiExam(models.Model):
    _name = 'bxi.exam'
    _description = 'Digital Exam'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    name = fields.Char(string='Exam Title', required=True, tracking=True)
    class_id = fields.Many2one('op.course', string='Class', required=True, tracking=True)
    subject_id = fields.Many2one('op.subject', string='Subject', required=True, tracking=True)
    teacher_id = fields.Many2one(
        'op.faculty', string='Teacher', tracking=True,
        default=lambda self: self.env['op.faculty'].search(
            [('user_id', '=', self.env.user.id)], limit=1),
        help='Left blank when created by someone without a linked Teacher record (e.g. via AI '
             'Assignment generation) - required before the exam can be published.')
    duration = fields.Integer(string='Duration (Minutes)', required=True, default=60)
    source = fields.Selection([
        ('manual', 'Manual'),
        ('ai', 'AI Generated'),
    ], string='Source', default='manual', required=True, readonly=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
    ], default='draft', required=True, tracking=True)
    question_ids = fields.One2many('bxi.exam.question', 'exam_id', string='Questions', copy=True)
    question_count = fields.Integer(string='No. of Questions', compute='_compute_question_stats', store=True)
    total_marks = fields.Float(string='Total Marks', compute='_compute_question_stats', store=True)
    active = fields.Boolean(default=True)

    @api.depends('question_ids.marks')
    def _compute_question_stats(self):
        for exam in self:
            exam.question_count = len(exam.question_ids)
            exam.total_marks = sum(exam.question_ids.mapped('marks'))

    def action_publish(self):
        for exam in self:
            if not exam.teacher_id:
                raise UserError(_('Assign a teacher to this exam before publishing it.'))
            if not exam.question_ids:
                raise UserError(_('Add at least one question before publishing this exam.'))
            errors = list(filter(None, exam.question_ids.mapped(lambda q: q._mcq_publish_error())))
            if errors:
                raise UserError('\n'.join(errors))
            exam.state = 'published'

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})
