# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class LabSession(models.Model):
    _name = 'lab.session'
    _description = 'Lab Session'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, start_time desc'

    name = fields.Char(string='Session Reference', copy=False, readonly=True, default=lambda self: _('New'))
    room_id = fields.Many2one('lab.room', string='Lab Room', required=True, tracking=True)
    course_id = fields.Many2one('op.course', string='Course', required=True)
    batch_id = fields.Many2one('op.batch', string='Batch', required=True)
    subject_id = fields.Many2one('op.subject', string='Subject')
    faculty_id = fields.Many2one('op.faculty', string='Instructor', required=True, tracking=True)
    experiment_id = fields.Many2one('lab.experiment', string='Experiment')

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    start_time = fields.Float(string='Start Time', required=True)
    end_time = fields.Float(string='End Time', required=True)

    student_ids = fields.Many2many('op.student', string='Students')
    attendance_ids = fields.One2many('lab.attendance', 'session_id', string='Attendance')
    issue_ids = fields.One2many('lab.equipment.issue', 'session_id', string='Equipment Issued')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('lab.session') or _('New')
        return super().create(vals_list)

    @api.onchange('batch_id')
    def _onchange_batch_id(self):
        if self.batch_id:
            self.student_ids = self.env['op.student'].search(
                [('course_detail_ids.batch_id', '=', self.batch_id.id)]
            )

    @api.constrains('room_id', 'date', 'start_time', 'end_time', 'state')
    def _check_room_conflict(self):
        for rec in self:
            if rec.state == 'cancelled' or not rec.room_id or not rec.date:
                continue
            if rec.start_time >= rec.end_time:
                raise ValidationError(_('End Time must be after Start Time.'))
            domain = [
                ('id', '!=', rec.id),
                ('room_id', '=', rec.room_id.id),
                ('date', '=', rec.date),
                ('state', '!=', 'cancelled'),
                ('start_time', '<', rec.end_time),
                ('end_time', '>', rec.start_time),
            ]
            conflict = self.search(domain, limit=1)
            if conflict:
                raise ValidationError(_(
                    'Room "%s" is already booked for "%s" on %s (%.2f - %.2f). '
                    'Please choose a different time or room.'
                ) % (rec.room_id.name, conflict.name, rec.date, conflict.start_time, conflict.end_time))

    @api.constrains('faculty_id', 'date', 'start_time', 'end_time', 'state')
    def _check_faculty_conflict(self):
        for rec in self:
            if rec.state == 'cancelled' or not rec.faculty_id or not rec.date:
                continue
            domain = [
                ('id', '!=', rec.id),
                ('faculty_id', '=', rec.faculty_id.id),
                ('date', '=', rec.date),
                ('state', '!=', 'cancelled'),
                ('start_time', '<', rec.end_time),
                ('end_time', '>', rec.start_time),
            ]
            conflict = self.search(domain, limit=1)
            if conflict:
                raise ValidationError(_(
                    'Instructor "%s" is already assigned to "%s" on %s (%.2f - %.2f). '
                    'Please choose a different time or instructor.'
                ) % (rec.faculty_id.name, conflict.name, rec.date, conflict.start_time, conflict.end_time))

    def action_confirm(self):
        for rec in self:
            rec.state = 'confirmed'
            rec._generate_attendance()
        return True

    def _generate_attendance(self):
        """Auto-generate attendance lines for all students in student_ids.
        Existing lines for students already present are left untouched;
        lines for students no longer in student_ids are removed.
        """
        Attendance = self.env['lab.attendance']
        for rec in self:
            existing = rec.attendance_ids
            existing_students = existing.mapped('student_id')
            # remove attendance for students no longer selected
            to_remove = existing.filtered(lambda a: a.student_id not in rec.student_ids)
            to_remove.unlink()
            # create attendance for newly added students
            new_students = rec.student_ids - existing_students
            for student in new_students:
                Attendance.create({
                    'session_id': rec.id,
                    'student_id': student.id,
                    'status': 'present',
                })

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})
