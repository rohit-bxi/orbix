# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Read-only Class / Section / Department / Status on the Student and
Parent forms, derived from enrolments (the requirement sheet's
"Department", "Class / Group" and "Status")."""
from odoo import api, fields, models

ENROLMENT_STATES = [('running', 'Running'), ('finished', 'Finished')]


class OpStudent(models.Model):
    _inherit = 'op.student'

    bxi_current_course_id = fields.Many2one(
        'op.course', string='Current Class', compute='_compute_bxi_current_enrolment')
    bxi_current_batch_id = fields.Many2one(
        'op.batch', string='Current Section', compute='_compute_bxi_current_enrolment')
    bxi_department_id = fields.Many2one(
        'op.department', string='Department', compute='_compute_bxi_current_enrolment',
        help="The department of the student's current class.")
    bxi_enrolment_state = fields.Selection(
        ENROLMENT_STATES, string='Enrolment Status', compute='_compute_bxi_current_enrolment',
        help='Status of the current enrolment (the running one, else the latest).')

    def _bxi_current_enrolment(self):
        """The running enrolment, else the latest one."""
        self.ensure_one()
        lines = self.sudo().course_detail_ids
        return lines.filtered(lambda line: line.state == 'running')[:1] or lines.sorted('id', reverse=True)[:1]

    @api.depends('course_detail_ids.state', 'course_detail_ids.course_id', 'course_detail_ids.batch_id')
    def _compute_bxi_current_enrolment(self):
        for student in self:
            line = student._bxi_current_enrolment() if student.id else self.env['op.student.course']
            student.bxi_current_course_id = line.course_id
            student.bxi_current_batch_id = line.batch_id
            student.bxi_department_id = line.course_id.department_id
            student.bxi_enrolment_state = line.state or False


class OpParent(models.Model):
    _inherit = 'op.parent'

    bxi_child_department_ids = fields.Many2many(
        'op.department', string='Department', compute='_compute_bxi_children_classes',
        help="Departments of the children's current classes.")
    bxi_child_course_ids = fields.Many2many(
        'op.course', string='Class', compute='_compute_bxi_children_classes')
    bxi_child_batch_ids = fields.Many2many(
        'op.batch', string='Class / Group', compute='_compute_bxi_children_classes',
        help="Sections the children are currently enrolled in.")

    @api.depends('student_ids')
    def _compute_bxi_children_classes(self):
        for parent in self:
            lines = parent.sudo().student_ids.course_detail_ids.filtered(lambda line: line.state == 'running')
            parent.bxi_child_department_ids = lines.course_id.department_id
            parent.bxi_child_course_ids = lines.course_id
            parent.bxi_child_batch_ids = lines.batch_id
