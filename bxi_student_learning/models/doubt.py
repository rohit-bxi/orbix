# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Doubts a student asks (the dashboard's "Smart Doubt Buddy / Ask Your
Tutor"): answered by the student's own subject teacher - no external AI."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

STATES = [('open', 'Open'), ('answered', 'Answered'), ('closed', 'Closed')]


class BxiStudentDoubt(models.Model):
    _name = 'bxi.student.doubt'
    _description = 'Student Doubt'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'
    _rec_name = 'question'

    student_id = fields.Many2one('op.student', string='Student', required=True, index=True, tracking=True)
    subject_id = fields.Many2one('op.subject', string='Subject', index=True, tracking=True)
    course_id = fields.Many2one('op.course', string='Class', index=True)
    batch_id = fields.Many2one('op.batch', string='Section', index=True)
    question = fields.Text(required=True)
    attachment_ids = fields.Many2many(
        'ir.attachment', 'bxi_student_doubt_attachment_rel', 'doubt_id', 'attachment_id', string='Attachments')
    teacher_id = fields.Many2one('op.faculty', string='Teacher', index=True, tracking=True,
                                 help='Who answers it: the subject teacher of the class, else the class teacher.')
    state = fields.Selection(STATES, default='open', required=True, index=True, tracking=True)
    answer = fields.Text(tracking=True)
    answered_by_id = fields.Many2one('res.users', string='Answered By', readonly=True)
    answered_at = fields.Datetime(readonly=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model
    def _bxi_teacher_for(self, enrollment, subject):
        """The teacher mapped to `subject` for the class (Subject Mapping),
        else the section's class teacher."""
        teacher = self.env['op.faculty']
        if subject and enrollment:
            mapping = self.env['bxi.subject.mapping'].sudo().search([
                ('subject_id', '=', subject.id), ('class_id', '=', enrollment.course_id.id)], limit=1)
            teacher = mapping.teacher_id
        if not teacher and enrollment and 'class_teacher_id' in enrollment.batch_id._fields:
            teacher = enrollment.batch_id.class_teacher_id
        return teacher

    def action_answer(self, answer, user):
        for doubt in self:
            if doubt.state == 'closed':
                raise UserError(_('This doubt is closed.'))
            doubt.write({'answer': answer, 'state': 'answered', 'answered_by_id': user.id,
                         'answered_at': fields.Datetime.now()})

    def action_close(self):
        self.write({'state': 'closed'})
