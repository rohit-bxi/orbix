# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The app's Settings screen (notification switches, theme, offline mode,
auto sync) and the two reminders those switches control: homework due
within a day and the student's daily study reminder."""
from datetime import timedelta

import pytz

from odoo import _, api, fields, models

from .push_triggers import _notify


def _school_time(env, value):
    """A UTC datetime in the school's time zone (the company's working
    calendar, else UTC): crons run as the superuser, whose own tz says
    nothing about the school."""
    tz = env.company.sudo().resource_calendar_id.tz or 'UTC'
    return pytz.utc.localize(value).astimezone(pytz.timezone(tz))

# Settings switch -> the bxi.notification categories it silences.
NOTIFICATION_SWITCHES = {
    'assignment_reminders': ('homework', 'homework_reminder'),
    'exam_notifications': ('exam',),
    'grade_updates': ('result',),
    'study_reminders': ('study_reminder',),
}
THEMES = [('light', 'Light'), ('dark', 'Dark'), ('auto', 'Auto')]
DONE_SUBMISSION_STATES = ('submit', 'accept')
STUDY_EXAM_DAYS = 3


class ResUsers(models.Model):
    _inherit = 'res.users'

    bxi_app_theme = fields.Selection(THEMES, string='App Theme', default='auto', copy=False)
    bxi_app_offline_mode = fields.Boolean(string='App Offline Mode', copy=False,
                                          help='Download content for offline access in the app.')
    bxi_app_auto_sync = fields.Boolean(string='App Auto Sync', default=True, copy=False)

    def _bxi_notification_switches(self):
        self.ensure_one()
        muted = self._bxi_muted_categories()
        return {key: not (set(categories) & muted) for key, categories in NOTIFICATION_SWITCHES.items()}

    def _bxi_set_notification_switches(self, switches):
        """`switches`: {key: bool} for keys of NOTIFICATION_SWITCHES; keys
        not sent keep their value."""
        self.ensure_one()
        muted = self._bxi_muted_categories()
        for key, enabled in switches.items():
            categories = set(NOTIFICATION_SWITCHES[key])
            muted = (muted - categories) if enabled else (muted | categories)
        self._bxi_set_muted_categories(muted)


def _already_sent(env, category, model, ids, since):
    """{(user_id, res_id)} already notified for `category` since `since`."""
    return {(n.user_id.id, n.res_id) for n in env['bxi.notification'].sudo().search([
        ('category', '=', category), ('res_model', '=', model), ('res_id', 'in', list(ids)),
        ('create_date', '>=', since)])}


class OpAssignment(models.Model):
    _inherit = 'op.assignment'

    @api.model
    def _cron_bxi_homework_reminders(self):
        """Daily: tell each student (and their parents) about homework due in
        the next 24 hours they have not handed in yet - once per homework."""
        now = fields.Datetime.now()
        assignments = self.sudo().search([
            ('state', '=', 'publish'), ('submission_date', '>', now),
            ('submission_date', '<=', now + timedelta(days=1))])
        if not assignments:
            return
        handed_in = {(s.assignment_id.id, s.student_id.id) for s in self.env['op.assignment.sub.line'].sudo().search([
            ('assignment_id', 'in', assignments.ids), ('state', 'in', DONE_SUBMISSION_STATES)])}
        sent = _already_sent(self.env, 'homework_reminder', self._name, assignments.ids, now - timedelta(days=2))
        today = _school_time(self.env, now).date()
        for assignment in assignments:
            students = assignment.allocation_ids.filtered(lambda s: (assignment.id, s.id) not in handed_in)
            users = students._bxi_family_users().filtered(lambda u: (u.id, assignment.id) not in sent)
            due = _school_time(self.env, assignment.submission_date)
            if due.date() == today:
                title = _('Due today: %s', assignment.name)
                body = _('"%(name)s" is due today at %(time)s. Hand it in on time.',
                         name=assignment.name, time=due.strftime('%I:%M %p'))
            else:
                title = _('Due tomorrow: %s', assignment.name)
                body = _('"%(name)s" is due tomorrow at %(time)s. Hand it in on time.',
                         name=assignment.name, time=due.strftime('%I:%M %p'))
            _notify(self.env, users, title, body, 'homework_reminder', assignment)


class OpStudent(models.Model):
    _inherit = 'op.student'

    @api.model
    def _cron_bxi_study_reminders(self):
        """Daily: a study reminder for each student login with exams in the
        next few days or homework still to hand in. Only the student - not
        the parents - and at most once a day."""
        now = fields.Datetime.now()
        enrollments = self.env['op.student.course'].sudo().search([
            ('state', '=', 'running'), ('student_id.user_id', '!=', False), ('student_id.user_id.active', '=', True)])
        if not enrollments:
            return
        exams = self.env['op.exam'].sudo().search([
            ('state', 'not in', ('cancel', 'done')), ('session_id.state', 'in', ('schedule', 'held')),
            ('start_time', '>=', now), ('start_time', '<=', now + timedelta(days=STUDY_EXAM_DAYS))], order='start_time')
        pending = self.env['op.assignment'].sudo().search([('state', '=', 'publish'), ('submission_date', '>=', now)])
        handed_in = {(s.assignment_id.id, s.student_id.id) for s in self.env['op.assignment.sub.line'].sudo().search([
            ('assignment_id', 'in', pending.ids), ('state', 'in', DONE_SUBMISSION_STATES)])}
        sent = _already_sent(self.env, 'study_reminder', self._name, enrollments.student_id.ids, now - timedelta(hours=20))
        for enrollment in enrollments:
            student = enrollment.student_id
            if (student.user_id.id, student.id) in sent:
                continue
            own_exams = exams.filtered(lambda e: e.session_id.course_id == enrollment.course_id and (
                not e.session_id.batch_id or e.session_id.batch_id == enrollment.batch_id))
            todo = pending.filtered(lambda a: student in a.allocation_ids and (a.id, student.id) not in handed_in)
            if not own_exams and not todo:
                continue
            parts = []
            if own_exams:
                parts.append(_('Revise %(subject)s - exam on %(date)s.', subject=own_exams[0].subject_id.name or own_exams[0].name,
                               date=_school_time(self.env, own_exams[0].start_time).strftime('%d %b')))
            if todo:
                parts.append(_('%s homework to finish.', len(todo)))
            _notify(self.env, student.user_id, _('Study reminder'), ' '.join(parts), 'study_reminder', student)
