# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""An exam across several sections (the app's Add / Edit Exam screen):
name, dates, sections ("Class 10 A", "Class 10 B") and subjects.

OpenEduCat's exam session covers one class and one section, and its
papers need times and marks the screen does not ask for. So a schedule
keeps one draft op.exam.session per section in step with it (name,
dates, exam type); exam staff then add the papers, rooms and marks on
those sessions as before, and hall tickets, date sheets and report cards
keep working unchanged."""
import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

SCHEDULE_STATES = [
    ('draft', 'Draft'),
    ('partly_scheduled', 'Partly Scheduled'),
    ('scheduled', 'Scheduled'),
    ('in_progress', 'In Progress'),
    ('done', 'Done'),
    ('cancelled', 'Cancelled'),
]


class ExamScheduleError(UserError):
    """A refusal the API reports with its own code and status."""

    def __init__(self, message, code, status=409):
        super().__init__(message)
        self.code = code
        self.status = status


class BxiExamSchedule(models.Model):
    _name = 'bxi.exam.schedule'
    _inherit = ['mail.thread']
    _description = 'Exam Schedule (one exam across sections)'
    _order = 'start_date desc, id desc'

    name = fields.Char('Exam Name', required=True, tracking=True)
    start_date = fields.Date('Start Date', required=True, tracking=True)
    end_date = fields.Date('End Date', required=True, tracking=True)
    batch_ids = fields.Many2many('op.batch', 'bxi_exam_schedule_batch_rel', 'schedule_id', 'batch_id',
                                 string='Classes', help='The sections sitting this exam.')
    subject_ids = fields.Many2many('op.subject', 'bxi_exam_schedule_subject_rel', 'schedule_id', 'subject_id',
                                   string='Subjects')
    exam_type_id = fields.Many2one('op.exam.type', string='Exam Type', required=True, tracking=True,
                                   default=lambda self: self._default_exam_type())
    session_ids = fields.One2many('op.exam.session', 'bxi_schedule_id', string='Sessions per Section')
    state = fields.Selection(SCHEDULE_STATES, string='Status', compute='_compute_state', store=True)
    paper_count = fields.Integer('Papers', compute='_compute_paper_count')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model
    def _default_exam_type(self):
        return self.env.ref('bxi_academic_management.exam_type_general', raise_if_not_found=False)

    @api.depends('session_ids.state')
    def _compute_state(self):
        for schedule in self:
            states = set(schedule.session_ids.mapped('state'))
            live = states - {'cancel'}
            if not states:
                schedule.state = 'draft'
            elif not live:
                schedule.state = 'cancelled'
            elif live == {'draft'}:
                schedule.state = 'draft'
            elif live == {'schedule'}:
                schedule.state = 'scheduled'
            elif live == {'done'}:
                schedule.state = 'done'
            elif live <= {'draft', 'schedule'}:
                schedule.state = 'partly_scheduled'
            else:
                schedule.state = 'in_progress'

    def _compute_paper_count(self):
        for schedule in self:
            schedule.paper_count = len(schedule.sudo().session_ids.exam_ids)

    # -- sync -------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        schedules = super().create(vals_list)
        schedules._bxi_sync_sessions()
        return schedules

    def write(self, vals):
        res = super().write(vals)
        if {'name', 'start_date', 'end_date', 'batch_ids', 'subject_ids', 'exam_type_id', 'active'} & set(vals):
            self._bxi_sync_sessions()
        return res

    def unlink(self):
        for schedule in self:
            sessions = schedule.sudo().with_context(active_test=False).session_ids
            if sessions.filtered(lambda s: s.state != 'draft') or sessions.exam_ids:
                raise ExamScheduleError(
                    _('%s has started (papers are set up or a section is scheduled): cancel it instead.',
                      schedule.name), 'exam_in_progress')
            sessions.unlink()
        return super().unlink()

    def _bxi_check(self):
        for schedule in self:
            if schedule.end_date < schedule.start_date:
                raise ExamScheduleError(_('End Date cannot be before Start Date.'), 'invalid_dates', 400)
            if not schedule.batch_ids:
                raise ExamScheduleError(_('Add at least one class.'), 'missing_section_ids', 400)
            if not schedule.subject_ids:
                raise ExamScheduleError(_('Add at least one subject.'), 'missing_subject_ids', 400)
            for batch in schedule.batch_ids:
                listed = batch.course_id.subject_ids
                outside = schedule.subject_ids - listed if listed else self.env['op.subject']
                if outside:
                    raise ExamScheduleError(
                        _('%(subjects)s is not a subject of %(class)s.',
                          subjects=', '.join(outside.mapped('name')), **{'class': batch.course_id.name}),
                        'subject_not_in_class', 400)
            others = self.sudo().search([
                ('id', '!=', schedule.id), ('name', '=ilike', schedule.name),
                ('batch_ids', 'in', schedule.batch_ids.ids),
                ('start_date', '<=', schedule.end_date), ('end_date', '>=', schedule.start_date)], limit=1)
            if others:
                raise ExamScheduleError(
                    _('%s already exists for one of these classes on overlapping dates.', schedule.name),
                    'exam_exists')

    def _bxi_sync_sessions(self):
        """Keep one session per section in step with the schedule."""
        self._bxi_check()
        Session = self.env['op.exam.session'].sudo()
        for schedule in self.sudo():
            sessions = schedule.with_context(active_test=False).session_ids
            # Sections taken off the exam.
            for session in sessions.filtered(lambda s: s.batch_id not in schedule.batch_ids):
                if session.state != 'draft' or session.exam_ids:
                    raise ExamScheduleError(
                        _('%s already has papers or is scheduled for this exam: it cannot be removed.',
                          session.batch_id.display_name), 'section_in_use')
                session.unlink()
            sessions = sessions.exists()
            # Subjects taken off the exam.
            papers = sessions.exam_ids.filtered(lambda e: e.state != 'cancel')
            dropped = papers.subject_id - schedule.subject_ids
            if dropped:
                raise ExamScheduleError(
                    _('Papers are already set up for %s: it cannot be removed.', ', '.join(dropped.mapped('name'))),
                    'subject_has_papers')
            # New dates must still hold every paper.
            first = datetime.datetime.combine(schedule.start_date, datetime.time.min)
            last = datetime.datetime.combine(schedule.end_date, datetime.time.max)
            outside = papers.filtered(lambda e: e.start_time < first or e.end_time > last)
            if outside:
                raise ExamScheduleError(
                    _('These papers fall outside the new dates: %s.', ', '.join(outside.mapped('name'))),
                    'papers_outside_dates')
            shared = {'name': schedule.name, 'start_date': schedule.start_date, 'end_date': schedule.end_date,
                      'exam_type': schedule.exam_type_id.id}
            for session in sessions.filtered(lambda s: s.state != 'cancel'):
                changed = {key: value for key, value in shared.items()
                           if (session[key].id if key == 'exam_type' else session[key]) != value}
                if changed:
                    session.write(changed)
            if sessions.filtered(lambda s: s.active != schedule.active):
                sessions.write({'active': schedule.active})
            for batch in schedule.batch_ids - sessions.batch_id:
                Session.create(dict(shared, course_id=batch.course_id.id, batch_id=batch.id,
                                    exam_code=self._bxi_next_session_code(), bxi_schedule_id=schedule.id,
                                    active=schedule.active))

    @api.model
    def _bxi_next_session_code(self):
        Session = self.env['op.exam.session'].sudo().with_context(active_test=False)
        Sequence = self.env['ir.sequence'].sudo()
        while True:
            code = Sequence.next_by_code('bxi.exam.schedule.session')
            if not code:
                raise UserError(_('The exam code sequence is missing: update Academic Management.'))
            if not Session.search_count([('exam_code', '=', code)], limit=1):
                return code


class OpExamSession(models.Model):
    _inherit = 'op.exam.session'

    bxi_schedule_id = fields.Many2one('bxi.exam.schedule', string='Exam Schedule', index=True, readonly=True,
                                      ondelete='set null', copy=False)


class OpExam(models.Model):
    _inherit = 'op.exam'

    @api.constrains('subject_id', 'session_id')
    def _check_bxi_schedule_subject(self):
        for exam in self:
            schedule = exam.session_id.bxi_schedule_id
            if schedule and exam.subject_id not in schedule.subject_ids:
                raise ValidationError(_('%(subject)s is not a subject of the exam %(exam)s.',
                                        subject=exam.subject_id.name, exam=schedule.name))
