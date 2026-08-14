# -*- coding: utf-8 -*-
from odoo import models, fields


class LabAttendance(models.Model):
    _name = 'lab.attendance'
    _description = 'Lab Session Attendance'
    _rec_name = 'student_id'

    session_id = fields.Many2one('lab.session', string='Session', required=True, ondelete='cascade')
    student_id = fields.Many2one('op.student', string='Student', required=True, ondelete='cascade')
    status = fields.Selection([
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
    ], string='Status', default='present', required=True)
    remark = fields.Char(string='Remark')
    date = fields.Date(related='session_id.date', string='Date', store=True)
    room_id = fields.Many2one(related='session_id.room_id', string='Lab Room', store=True)

    _sql_constraints = [
        ('session_student_uniq', 'unique(session_id, student_id)',
         'Attendance for this student already exists for this session!'),
    ]
