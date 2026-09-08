# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import api, fields, models


class BxiMessageThread(models.Model):
    """Always scoped to exactly one parent, one teacher and one student -
    there is no group chat here, matching the single "Parent-Teacher
    Communication" feature the Figma design specifies. Re-requesting a
    thread for the same (student, parent, teacher) triple reuses the
    existing one rather than creating a duplicate.
    """
    _name = 'bxi.message.thread'
    _description = 'Parent-Teacher Message Thread'
    _order = 'last_message_at desc'

    student_id = fields.Many2one('op.student', required=True, index=True)
    parent_id = fields.Many2one('op.parent', required=True, index=True)
    teacher_id = fields.Many2one('op.faculty', required=True, index=True)
    subject = fields.Char()
    message_ids = fields.One2many('bxi.message', 'thread_id')
    message_count = fields.Integer(compute='_compute_message_stats', store=True)
    last_message_at = fields.Datetime(compute='_compute_message_stats', store=True)

    _sql_constraints = [
        ('thread_unique', 'unique(student_id, parent_id, teacher_id)',
         'A thread for this student/parent/teacher combination already exists.'),
    ]

    @api.depends('message_ids.create_date')
    def _compute_message_stats(self):
        for thread in self:
            thread.message_count = len(thread.message_ids)
            thread.last_message_at = max(thread.message_ids.mapped('create_date'), default=thread.create_date)

    @api.model
    def _get_or_create(self, student, parent, teacher):
        thread = self.sudo().search([
            ('student_id', '=', student.id), ('parent_id', '=', parent.id), ('teacher_id', '=', teacher.id),
        ], limit=1)
        if thread:
            return thread
        return self.sudo().create({
            'student_id': student.id, 'parent_id': parent.id, 'teacher_id': teacher.id,
        })

    def _unread_count_for(self, user):
        return self.env['bxi.message'].sudo().search_count([
            ('thread_id', '=', self.id),
            ('sender_user_id', '!=', user.id),
            ('read_at', '=', False),
        ])

    def _mark_read_for(self, user):
        unread = self.env['bxi.message'].sudo().search([
            ('thread_id', '=', self.id),
            ('sender_user_id', '!=', user.id),
            ('read_at', '=', False),
        ])
        unread.write({'read_at': fields.Datetime.now()})
