# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

EMPLOYMENT_STATUSES = [
    ('active', 'Active'),
    ('on_leave', 'On Leave'),
    ('resigned', 'Resigned'),
]


class OpFaculty(models.Model):
    _inherit = 'op.faculty'

    emergency_contact_relation = fields.Char(string='Emergency Contact Relation')
    certifications = fields.Text(string='Certifications', help='e.g. B.Ed, CTET, first-aid training.')
    staff_notes = fields.Text(string='Notes')
    assigned_course_ids = fields.Many2many(
        'op.course', 'op_faculty_assigned_course_rel', 'faculty_id', 'course_id', string='Assigned Classes')
    assigned_batch_ids = fields.Many2many(
        'op.batch', 'op_faculty_assigned_batch_rel', 'faculty_id', 'batch_id', string='Assigned Sections',
        domain="[('course_id', 'in', assigned_course_ids)]")
    remaining_weekly_periods = fields.Integer(
        string='Remaining Periods', compute='_compute_remaining_weekly_periods',
        help='Weekly period limit minus the periods already on the timetable (never below zero).')
    timetable_auto_assign = fields.Boolean(
        string='Timetable Auto Assign',
        help='Schedule this teacher\'s periods automatically from their availability. '
             'Stored for the scheduler; periods are still assigned by hand today.')
    designation_id = fields.Many2one('hr.job', string='Designation', tracking=True)
    responsibility_ids = fields.Many2many(
        'bxi.staff.responsibility', 'op_faculty_staff_responsibility_rel', 'faculty_id', 'responsibility_id',
        string='Other Responsibilities')
    employment_status = fields.Selection(
        EMPLOYMENT_STATUSES, string='Status', default='active', required=True, tracking=True,
        help='Employment status. Whether the teacher can sign in is controlled by their login, not this field.')

    # Lesson & evaluation permissions. They narrow what a teacher may do in
    # the app; office staff and coordinators are never limited by them.
    # New columns default to True, so existing teachers keep their access.
    can_create_lesson_plans = fields.Boolean(string='Can Create Lesson Plans', default=True, tracking=True)
    can_assign_homework = fields.Boolean(string='Can Assign Homework', default=True, tracking=True)
    can_evaluate_assignments = fields.Boolean(string='Can Evaluate Assignments', default=True, tracking=True)
    can_enter_exam_marks = fields.Boolean(string='Can Enter Exam Marks', default=True, tracking=True)
    can_access_reports = fields.Boolean(string='Can Access Reports', default=True, tracking=True)

    document_ids = fields.One2many('bxi.faculty.document', 'faculty_id', string='Documents')
    document_count = fields.Integer(compute='_compute_document_count')

    @api.depends('document_ids')
    def _compute_document_count(self):
        for faculty in self:
            faculty.document_count = len(faculty.document_ids)

    @api.model_create_multi
    def create(self, vals_list):
        faculties = super().create(vals_list)
        faculties._sync_designation_to_employee()
        return faculties

    def write(self, vals):
        res = super().write(vals)
        if 'designation_id' in vals or 'emp_id' in vals:
            self._sync_designation_to_employee()
        return res

    def _sync_designation_to_employee(self):
        """The designation is the HR Job Position: keep the linked
        employee's job in step."""
        for faculty in self.sudo().filtered(lambda f: f.emp_id and f.designation_id):
            if faculty.emp_id.job_id != faculty.designation_id:
                faculty.emp_id.job_id = faculty.designation_id

    @api.depends('max_weekly_periods', 'weekly_period_count')
    def _compute_remaining_weekly_periods(self):
        for faculty in self:
            faculty.remaining_weekly_periods = max((faculty.max_weekly_periods or 0) - faculty.weekly_period_count, 0)

    @api.constrains('assigned_course_ids', 'assigned_batch_ids')
    def _check_assigned_sections(self):
        for faculty in self:
            stray = faculty.assigned_batch_ids.filtered(lambda b: b.course_id not in faculty.assigned_course_ids)
            if stray:
                raise ValidationError(_(
                    'Section(s) %(sections)s belong to a class that is not assigned to %(teacher)s.',
                    sections=', '.join(stray.mapped('name')), teacher=faculty.name))

    @api.constrains('max_weekly_periods')
    def _check_max_weekly_periods(self):
        for faculty in self:
            if faculty.max_weekly_periods < 0:
                raise ValidationError(_('The weekly period limit cannot be negative.'))
