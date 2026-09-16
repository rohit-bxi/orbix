# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, http
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.exceptions import MissingError
from odoo.http import request

# Marksheet lines are only shown to the student once the register has been
# validated by staff - a draft register is provisional/ungraded data that
# shouldn't leak to a portal user before publication.
MARKSHEET_PUBLISHED_STATE = 'validated'
ASSIGNMENT_VISIBLE_STATES = ('publish', 'finish')


class StudentPortal(CustomerPortal):

    # ------------------------------------------------------------------
    # Access resolution - shared by every route below and reused as-is by
    # bxi_parent_portal (which passes the child's student_id explicitly).
    # ------------------------------------------------------------------
    def _resolve_target_student(self, student_id=None):
        """Return the op.student the current user is allowed to view.

        With no student_id, resolves to "the logged-in student themself".
        With a student_id, relies entirely on ir.rule (student_parent_login_rule
        in openeducat_parent: self or one of the caller's children) - this
        method never uses sudo() for the actual access check, only to tell
        a genuinely missing record apart from an access-denied one.
        """
        Student = request.env['op.student']
        if student_id:
            student = Student.browse(int(student_id))
            if not student.sudo().exists():
                raise MissingError("This student record does not exist.")
            student.check_access('read')
            return student.sudo()
        student = Student.sudo().search([('user_id', '=', request.env.uid)], limit=1)
        if not student:
            raise MissingError("No student profile is linked to this account.")
        return student

    # ------------------------------------------------------------------
    # Aggregation helpers - kept here (not on the model) since they only
    # ever back a portal page and would otherwise add cross-module fields
    # to op.student for a purely presentational need.
    # ------------------------------------------------------------------
    def _attendance_summary(self, student):
        lines = request.env['op.attendance.line'].search([
            ('student_id', '=', student.id),
            ('state', '=', 'done'),
        ])
        total = len(lines)
        present = len(lines.filtered('present'))
        return {
            'total': total,
            'present': present,
            'absent': len(lines.filtered('absent')),
            'late': len(lines.filtered('late')),
            'excused': len(lines.filtered('excused')),
            'percentage': round((present / total) * 100, 1) if total else 0.0,
        }

    def _upcoming_sessions(self, student, limit=5):
        now = fields.Datetime.now()
        return request.env['op.session'].search([
            ('student_ids', 'in', student.id),
            ('start_datetime', '>=', now),
        ], order='start_datetime asc', limit=limit)

    def _pending_assignment_count(self, student):
        return request.env['op.assignment'].search_count([
            ('allocation_ids', 'in', student.id),
            ('state', 'in', ASSIGNMENT_VISIBLE_STATES),
            ('submission_date', '>=', fields.Datetime.now()),
        ])

    def _fees_due_total(self, student):
        details = request.env['op.student.fees.details'].search([
            ('student_id', '=', student.id),
            ('invoice_state', 'in', ('draft', 'posted')),
        ])
        return sum(details.mapped('invoice_id.amount_residual'))

    # ------------------------------------------------------------------
    # Portal home tile
    # ------------------------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        student = request.env['op.student'].sudo().search(
            [('user_id', '=', request.env.uid)], limit=1)
        if student:
            values['academics_student'] = student
            values['academics_attendance'] = self._attendance_summary(student)
            values['academics_upcoming'] = self._upcoming_sessions(student, limit=1)
            values['academics_pending_assignments'] = self._pending_assignment_count(student)
            values['academics_fees_due'] = self._fees_due_total(student)
        return values

    # ------------------------------------------------------------------
    # Routes - each accepts an optional student_id so bxi_parent_portal can
    # link straight into these same pages for a specific child.
    # ------------------------------------------------------------------
    @http.route(['/my/academics', '/my/academics/<int:student_id>'],
                type='http', auth='user', website=True)
    def portal_academics_home(self, student_id=None, **kw):
        student = self._resolve_target_student(student_id)
        return request.render('bxi_student_portal.portal_academics_home', {
            'student': student,
            'attendance': self._attendance_summary(student),
            'upcoming_sessions': self._upcoming_sessions(student),
            'pending_assignments': self._pending_assignment_count(student),
            'fees_due': self._fees_due_total(student),
            'page_name': 'academics',
            'student_id': student_id,
        })

    @http.route(['/my/academics/attendance', '/my/academics/<int:student_id>/attendance'],
                type='http', auth='user', website=True)
    def portal_academics_attendance(self, student_id=None, date_from=None, date_to=None, **kw):
        student = self._resolve_target_student(student_id)
        domain = [('student_id', '=', student.id), ('state', '=', 'done')]
        if date_from:
            domain.append(('attendance_date', '>=', date_from))
        if date_to:
            domain.append(('attendance_date', '<=', date_to))
        lines = request.env['op.attendance.line'].search(domain, order='attendance_date desc')
        return request.render('bxi_student_portal.portal_academics_attendance', {
            'student': student,
            'lines': lines,
            'summary': self._attendance_summary(student),
            'date_from': date_from,
            'date_to': date_to,
            'page_name': 'academics',
            'student_id': student_id,
        })

    @http.route(['/my/academics/timetable', '/my/academics/<int:student_id>/timetable'],
                type='http', auth='user', website=True)
    def portal_academics_timetable(self, student_id=None, **kw):
        student = self._resolve_target_student(student_id)
        sessions = request.env['op.session'].search(
            [('student_ids', 'in', student.id)], order='start_datetime asc')
        return request.render('bxi_student_portal.portal_academics_timetable', {
            'student': student,
            'sessions': sessions,
            'page_name': 'academics',
            'student_id': student_id,
        })

    @http.route(['/my/academics/exams', '/my/academics/<int:student_id>/exams'],
                type='http', auth='user', website=True)
    def portal_academics_exams(self, student_id=None, **kw):
        student = self._resolve_target_student(student_id)
        marksheets = request.env['op.marksheet.line'].search([
            ('student_id', '=', student.id),
            ('marksheet_reg_id.state', '=', MARKSHEET_PUBLISHED_STATE),
        ], order='generated_date desc')
        return request.render('bxi_student_portal.portal_academics_exams', {
            'student': student,
            'marksheets': marksheets,
            'page_name': 'academics',
            'student_id': student_id,
        })

    @http.route(['/my/academics/assignments', '/my/academics/<int:student_id>/assignments'],
                type='http', auth='user', website=True)
    def portal_academics_assignments(self, student_id=None, **kw):
        student = self._resolve_target_student(student_id)
        assignments = request.env['op.assignment'].search([
            ('allocation_ids', 'in', student.id),
            ('state', 'in', ASSIGNMENT_VISIBLE_STATES),
        ], order='submission_date desc')
        submissions = request.env['op.assignment.sub.line'].search([
            ('student_id', '=', student.id),
            ('assignment_id', 'in', assignments.ids),
        ])
        submission_by_assignment = {sub.assignment_id.id: sub for sub in submissions}
        return request.render('bxi_student_portal.portal_academics_assignments', {
            'student': student,
            'assignments': assignments,
            'submission_by_assignment': submission_by_assignment,
            'page_name': 'academics',
            'student_id': student_id,
        })

    @http.route(['/my/academics/library', '/my/academics/<int:student_id>/library'],
                type='http', auth='user', website=True)
    def portal_academics_library(self, student_id=None, **kw):
        student = self._resolve_target_student(student_id)
        movements = request.env['op.media.movement'].search(
            [('student_id', '=', student.id)], order='issued_date desc')
        today = fields.Date.today()
        return request.render('bxi_student_portal.portal_academics_library', {
            'student': student,
            'movements': movements,
            'today': today,
            'page_name': 'academics',
            'student_id': student_id,
        })

    @http.route(['/my/academics/fees', '/my/academics/<int:student_id>/fees'],
                type='http', auth='user', website=True)
    def portal_academics_fees(self, student_id=None, **kw):
        student = self._resolve_target_student(student_id)
        details = request.env['op.student.fees.details'].search(
            [('student_id', '=', student.id)], order='date desc')
        return request.render('bxi_student_portal.portal_academics_fees', {
            'student': student,
            'details': details,
            'due_total': self._fees_due_total(student),
            'page_name': 'academics',
            'student_id': student_id,
        })
