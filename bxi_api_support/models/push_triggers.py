# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""App inbox/push notifications for the school events families and
teachers act on. Each hook only calls bxi.notification._notify(); the push
itself is sent later by bxi_notification_gateway's cron, so none of these
add latency to the action that triggers them."""
from datetime import timedelta

from odoo import _, api, fields, models

FEE_DUE_REMINDER_DAYS = 3


def _notify(env, users, title, body, category, record):
    return env['bxi.notification'].sudo()._notify(users, title, body, category=category, record=record)


class OpStudent(models.Model):
    _inherit = 'op.student'

    def _bxi_family_users(self):
        """Active logins of these students and of their parents."""
        parents = self.env['op.parent'].sudo().search([('student_ids', 'in', self.ids)])
        return (self.sudo().user_id | parents.user_id).filtered('active')


class BxiAnnouncement(models.Model):
    _inherit = 'bxi.announcement'

    def _dispatch_channels(self):
        res = super()._dispatch_channels()
        if self.channel_push:
            partners = self._resolve_recipient_partners()
            users = partners.user_ids
            # The announcement resolves students; their parents are the
            # ones holding the app for younger children.
            students = self.env['op.student'].sudo().search([('partner_id', 'in', partners.ids)])
            users |= students._bxi_family_users()
            _notify(self.env, users, self.title, self.body, 'announcement', self)
        return res


class BxiMessage(models.Model):
    _inherit = 'bxi.message'

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        for message in messages:
            thread = message.thread_id.sudo()
            recipients = (thread.parent_id.user_id | thread.teacher_id.user_id) - message.sender_user_id
            _notify(self.env, recipients, _('New message from %s', message.sender_user_id.name),
                    (message.body or '')[:200], 'message', thread)
        return messages


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    @api.model_create_multi
    def create(self, vals_list):
        attendances = super().create(vals_list)
        attendances.filtered(lambda a: a.status == 'absent')._bxi_notify_absence()
        return attendances

    def write(self, vals):
        was_absent = self.filtered(lambda a: a.status == 'absent') if vals.get('status') == 'absent' else self.browse()
        res = super().write(vals)
        if vals.get('status') == 'absent':
            (self - was_absent)._bxi_notify_absence()
        return res

    def _bxi_notify_absence(self):
        """At most one absence notice per student per day, however many
        periods they are marked absent for - and only for today's periods,
        so correcting an old register or importing history stays silent."""
        if self.env.context.get('bxi_no_notify'):
            return
        Notification = self.env['bxi.notification'].sudo()
        today = fields.Date.context_today(self)
        today_start = fields.Datetime.to_datetime(today)
        for attendance in self.filtered('student_id'):
            day = attendance.sudo().session_id.session_date or (
                attendance.check_in and fields.Datetime.context_timestamp(attendance, attendance.check_in).date())
            if day != today:
                continue
            student = attendance.student_id
            if Notification.search_count([
                ('category', '=', 'absence'), ('res_model', '=', 'op.student'), ('res_id', '=', student.id),
                ('create_date', '>=', today_start),
            ]):
                continue
            session = attendance.sudo().session_id
            body = _('%(student)s was marked absent for %(subject)s today.',
                     student=student.name, subject=session.subject_id.name or _('a class'))
            _notify(self.env, student._bxi_family_users(), _('Absence: %s', student.name), body, 'absence', student)


class OpAssignment(models.Model):
    _inherit = 'op.assignment'

    def act_publish(self):
        res = super().act_publish()
        for assignment in self:
            students = assignment.sudo().allocation_ids
            _notify(self.env, students._bxi_family_users(), _('New homework: %s', assignment.name),
                    _('Due %s', fields.Datetime.to_string(assignment.submission_date) or '-'), 'homework', assignment)
        return res


class OpMarksheetRegister(models.Model):
    _inherit = 'op.marksheet.register'

    def action_validate(self):
        res = super().action_validate()
        for register in self:
            students = register.sudo().marksheet_line.student_id
            _notify(self.env, students._bxi_family_users(), _('Results published'),
                    register.exam_session_id.display_name or register.name, 'result', register)
        return res


class RteLotteryBatch(models.Model):
    _inherit = 'rte.lottery.batch'

    def action_publish(self):
        res = super().action_publish()
        for batch in self:
            for result in batch.sudo().result_ids:
                parent_user = result.admission_id.rte_parent_id.user_id
                _notify(self.env, parent_user, _('RTE lottery result published'),
                        _('Check the result for %s in the app.', result.admission_id.name or ''),
                        'rte_lottery', result.admission_id)
        return res


class OpCertificate(models.Model):
    _inherit = 'op.certificate'

    def action_issue(self):
        res = super().action_issue()
        for certificate in self:
            _notify(self.env, certificate.sudo().student_id._bxi_family_users(),
                    _('Certificate issued: %s', certificate.certificate_type_id.name),
                    certificate.display_name, 'certificate', certificate)
        return res


class OpStudentFeesDetails(models.Model):
    _inherit = 'op.student.fees.details'

    @api.model
    def _cron_bxi_fee_due_reminders(self):
        """Daily: remind families of fee lines due in the next few days,
        once per fee line."""
        today = fields.Date.context_today(self)
        details = self.sudo().search([
            ('date', '>=', today), ('date', '<=', today + timedelta(days=FEE_DUE_REMINDER_DAYS)),
            ('amount_pending', '>', 0),
        ])
        already = set(self.env['bxi.notification'].sudo().search([
            ('category', '=', 'fee_due'), ('res_model', '=', self._name), ('res_id', 'in', details.ids),
        ]).mapped('res_id'))
        for detail in details.filtered(lambda d: d.id not in already):
            _notify(self.env, detail.student_id._bxi_family_users(), _('Fee due on %s', detail.date),
                    _('%(amount)s pending for %(student)s.', amount=detail.amount_pending, student=detail.student_id.name),
                    'fee_due', detail)
