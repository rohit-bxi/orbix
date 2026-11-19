# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class BxiPtmMeeting(models.Model):
    _name = 'bxi.ptm.meeting'
    _description = 'Parent-Teacher Meeting'
    _inherit = ['mail.thread']
    _order = 'start_datetime desc'

    name = fields.Char('PTM Name', required=True, tracking=True)
    start_datetime = fields.Datetime('Starts On', required=True, tracking=True)
    end_datetime = fields.Datetime('Ends On', required=True, tracking=True)
    venue = fields.Char('Venue', required=True, tracking=True)
    class_ids = fields.Many2many('op.course', string='Classes', required=True, tracking=True)
    batch_ids = fields.Many2many(
        'op.batch', 'bxi_ptm_meeting_batch_rel', 'meeting_id', 'batch_id', string='Sections', tracking=True,
        help='Only these sections of their classes are invited (the app\'s "Class 10 A" chips). A class '
             'with no section chosen here is invited whole.')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    parent_ids = fields.Many2many(
        'op.parent', string='Parents Notified',
        compute='_compute_parent_ids', store=True,
        help='Parents of every student currently enrolled (running) in any of the selected '
             'Classes. Drives both the portal read-access rule and who gets notified.')
    teacher_ids = fields.Many2many(
        'op.faculty', string='Teachers Notified',
        compute='_compute_teacher_ids', store=True,
        help='Teachers mapped (via Subject Mapping) to any of the selected Classes. There is '
             'no dedicated "assigned teacher" field on a PTM meeting - it is a class-wide '
             'notice, not a per-teacher booking - so eligibility is derived, not set directly.')

    @api.constrains('start_datetime', 'end_datetime')
    def _check_datetime_order(self):
        for meeting in self:
            if meeting.start_datetime and meeting.end_datetime \
                    and meeting.end_datetime <= meeting.start_datetime:
                raise ValidationError(_('End time must be after start time.'))

    @api.constrains('class_ids', 'batch_ids')
    def _check_sections_in_classes(self):
        for meeting in self:
            outside = meeting.batch_ids.filtered(lambda b: b.course_id not in meeting.class_ids)
            if outside:
                raise ValidationError(_('Add the class of %s too.', ', '.join(outside.mapped('display_name'))))

    def _bxi_covers(self, courses, batches):
        """Whether this meeting invites a student of one of `courses`,
        in one of `batches` (a class with sections chosen invites only
        those sections)."""
        self.ensure_one()
        for course in self.class_ids & courses:
            chosen = self.batch_ids.filtered(lambda b, c=course: b.course_id == c)
            if not chosen or chosen & batches:
                return True
        return False

    def _bxi_enrollment_domain(self):
        self.ensure_one()
        whole = self.class_ids - self.batch_ids.course_id
        domain = [('state', '=', 'running'), '|', ('course_id', 'in', whole.ids), ('batch_id', 'in', self.batch_ids.ids)]
        return domain

    @api.depends('class_ids', 'batch_ids')
    def _compute_parent_ids(self):
        Enrollment = self.env['op.student.course']
        for meeting in self:
            enrollments = Enrollment.search(meeting._bxi_enrollment_domain())
            meeting.parent_ids = enrollments.student_id.parent_ids

    @api.depends('class_ids')
    def _compute_teacher_ids(self):
        Mapping = self.env['bxi.subject.mapping']
        for meeting in self:
            meeting.teacher_ids = Mapping.search(
                [('class_id', 'in', meeting.class_ids.ids)]).teacher_id

    @api.model_create_multi
    def create(self, vals_list):
        meetings = super().create(vals_list)
        meetings._dispatch_notifications()
        return meetings

    def write(self, vals):
        should_notify = bool({'start_datetime', 'end_datetime', 'venue', 'class_ids', 'batch_ids'} & set(vals))
        res = super().write(vals)
        if should_notify:
            self._dispatch_notifications()
        return res

    def _dispatch_notifications(self):
        """Interim: direct mail.template send, mirroring bxi_school_notice's
        _dispatch_email_notification(). Once a shared notification-gateway
        dispatcher (e.g. bxi.notification.send) exists, swap this method's
        body for a single call into it - create()/write() above would not
        need to change.
        """
        template = self.env.ref(
            'bxi_academic_management.mail_template_ptm_meeting', raise_if_not_found=False)
        if not template:
            return
        for meeting in self:
            partners = meeting.parent_ids.name | meeting.teacher_ids.partner_id
            mailed = partners.filtered('email')
            if partners:
                meeting.message_subscribe(partner_ids=partners.ids)
            for partner in mailed:
                template.send_mail(
                    meeting.id, force_send=False,
                    email_values={'email_to': partner.email}, email_layout_xmlid=False)
            meeting.message_post(
                body=_(
                    'PTM notification emailed to %(count)s of %(total)s recipient(s).',
                    count=len(mailed), total=len(partners)),
                subtype_xmlid='mail.mt_note')
