# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Read-only Class / Section / Department / Status on the Student and
Parent forms, derived from enrolments (the requirement sheet's
"Department", "Class / Group" and "Status")."""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

ENROLMENT_STATES = [('running', 'Running'), ('finished', 'Finished')]


class OpStudentCourse(models.Model):
    _inherit = 'op.student.course'

    bxi_finished_order = fields.Integer(
        string='Finished Order', readonly=True, copy=False,
        help="Set when this enrolment is finished: 1 + the highest value among the student's other "
             "enrolments, so the one finished last is known (setting a student back to running "
             "reopens it). 0 for enrolments finished before this was recorded.")

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.filtered(lambda line: line.state == 'finished')._bxi_stamp_finished()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') == 'finished':
            self._bxi_stamp_finished()
        return res

    def _bxi_stamp_finished(self):
        for line in self.sudo():
            others = line.student_id.course_detail_ids - line
            line.bxi_finished_order = max(others.mapped('bxi_finished_order') or [0]) + 1


class OpStudent(models.Model):
    _inherit = 'op.student'

    bxi_is_draft = fields.Boolean(
        string='Draft', index=True, copy=False, readonly=True,
        help="Saved with \"Save Draft\" on the app's Add New Student screen: kept archived (so it is left out "
             "of every list, attendance and fee) with no enrolment and no login until it is completed.")
    # The class / section / roll number / status chosen on a draft: the
    # enrolment itself is only created when the draft is completed.
    bxi_draft_course_id = fields.Many2one('op.course', string='Draft Class', copy=False, readonly=True)
    bxi_draft_batch_id = fields.Many2one('op.batch', string='Draft Section', copy=False, readonly=True)
    bxi_draft_roll_number = fields.Char(string='Draft Roll Number', copy=False, readonly=True)
    bxi_draft_state = fields.Selection(ENROLMENT_STATES, string='Draft Enrolment Status', copy=False, readonly=True)

    bxi_current_course_id = fields.Many2one(
        'op.course', string='Current Class', compute='_compute_bxi_current_enrolment')
    bxi_current_batch_id = fields.Many2one(
        'op.batch', string='Current Section', compute='_compute_bxi_current_enrolment')
    bxi_department_id = fields.Many2one(
        'op.department', string='Department', compute='_compute_bxi_current_enrolment',
        help="The department of the student's current class.")
    bxi_enrolment_state = fields.Selection(
        ENROLMENT_STATES, string='Enrolment Status', compute='_compute_bxi_current_enrolment',
        help='Status of the current enrolment (the running one, else the one finished last).')

    def _bxi_current_enrolment(self):
        """The running enrolment, else the one finished last (by
        bxi_finished_order, then the newest for enrolments finished before
        that was recorded). After transfers A -> B -> A, finishing A and
        setting the student running again reopens A, not B."""
        self.ensure_one()
        lines = self.sudo().course_detail_ids
        return lines.filtered(lambda line: line.state == 'running')[:1] or \
            lines.sorted(lambda line: (line.bxi_finished_order, line.id), reverse=True)[:1]

    @api.depends('course_detail_ids.state', 'course_detail_ids.course_id', 'course_detail_ids.batch_id',
                 'course_detail_ids.bxi_finished_order')
    def _compute_bxi_current_enrolment(self):
        for student in self:
            line = student._bxi_current_enrolment() if student.id else self.env['op.student.course']
            student.bxi_current_course_id = line.course_id
            student.bxi_current_batch_id = line.batch_id
            student.bxi_department_id = line.course_id.department_id
            student.bxi_enrolment_state = line.state or False


class OpParent(models.Model):
    _inherit = 'op.parent'

    # A draft (the app's "Save Draft") may not have a child or a
    # relationship yet: required only once it is a real parent (see
    # _check_bxi_complete).
    student_ids = fields.Many2many(required=False)
    relationship_id = fields.Many2one(required=False)
    bxi_is_draft = fields.Boolean(
        string='Draft', index=True, copy=False, readonly=True,
        help="Saved with \"Save Draft\" on the app's Add Parent screen: kept archived with no login until it is "
             "completed.")
    # The Add / Edit Parent screen's Additional Documents.
    bxi_aadhaar_card_ids = fields.Many2many(
        'ir.attachment', 'op_parent_bxi_aadhaar_card_rel', 'parent_id', 'attachment_id', string='Aadhaar Card')
    bxi_pan_card_ids = fields.Many2many(
        'ir.attachment', 'op_parent_bxi_pan_card_rel', 'parent_id', 'attachment_id', string='PAN Card')
    bxi_id_proof_ids = fields.Many2many(
        'ir.attachment', 'op_parent_bxi_id_proof_rel', 'parent_id', 'attachment_id', string='ID Proof')

    @api.constrains('student_ids', 'relationship_id', 'bxi_is_draft')
    def _check_bxi_complete(self):
        # Archived students count: a student draft gets its parent too.
        for parent in self.with_context(active_test=False):
            if parent.bxi_is_draft:
                continue
            if not parent.student_ids:
                raise ValidationError(_('Link at least one student to %s.', parent.name.name))
            if not parent.relationship_id:
                raise ValidationError(_('Set the relation with the student for %s.', parent.name.name))

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
