# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Study notes a teacher publishes for a subject and class (the student
app's Notes and Note Details screens): content, key points, attachments,
comments and bookmarks."""
import re

from odoo import api, fields, models

WORDS_PER_MINUTE = 200
PRIORITIES = [('normal', 'Normal'), ('high', 'High')]


class BxiStudyNoteTag(models.Model):
    _name = 'bxi.study.note.tag'
    _description = 'Study Note Tag'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    color = fields.Integer()

    _unique_name = models.Constraint('unique(name)', 'This tag already exists.')


class BxiStudyNote(models.Model):
    _name = 'bxi.study.note'
    _description = 'Study Note'
    _inherit = ['mail.thread']
    _order = 'publish_date desc, id desc'

    name = fields.Char('Title', required=True, tracking=True)
    subject_id = fields.Many2one('op.subject', string='Subject', required=True, index=True, tracking=True)
    course_id = fields.Many2one('op.course', string='Class', required=True, index=True, tracking=True)
    batch_ids = fields.Many2many(
        'op.batch', 'bxi_study_note_batch_rel', 'note_id', 'batch_id', string='Sections',
        help='Only these sections see the note; leave empty for the whole class.')
    faculty_id = fields.Many2one(
        'op.faculty', string='Teacher', required=True, index=True, tracking=True,
        default=lambda self: self.env['op.faculty'].search([('user_id', '=', self.env.uid)], limit=1))
    chapter = fields.Char('Chapter / Unit')
    priority = fields.Selection(PRIORITIES, default='normal', required=True, tracking=True)
    tag_ids = fields.Many2many('bxi.study.note.tag', string='Tags')
    summary = fields.Text('Summary', help='The short description shown on the note card.')
    key_points = fields.Text('Key Points', help='One point per line.')
    content = fields.Html('Content', sanitize=True)
    attachment_ids = fields.Many2many(
        'ir.attachment', 'bxi_study_note_attachment_rel', 'note_id', 'attachment_id', string='Attachments')
    state = fields.Selection([('draft', 'Draft'), ('published', 'Published')], default='draft', required=True,
                             tracking=True)
    publish_date = fields.Datetime('Published On', copy=False, tracking=True)
    read_minutes = fields.Integer('Read Time (min)', compute='_compute_read_minutes', store=True)
    bookmark_user_ids = fields.Many2many(
        'res.users', 'bxi_study_note_bookmark_rel', 'note_id', 'user_id', string='Bookmarked By', copy=False)
    comment_ids = fields.One2many('bxi.study.note.comment', 'note_id', string='Comments')
    comment_count = fields.Integer(compute='_compute_comment_count')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('content', 'summary', 'key_points')
    def _compute_read_minutes(self):
        for note in self:
            text = re.sub(r'<[^>]+>', ' ', note.content or '') + ' ' + (note.summary or '') + ' ' + (note.key_points or '')
            words = len(text.split())
            note.read_minutes = max(1, -(-words // WORDS_PER_MINUTE)) if words else 0

    def _compute_comment_count(self):
        for note in self:
            note.comment_count = len(note.comment_ids.filtered(lambda c: not c.hidden))

    def action_publish(self):
        for note in self:
            note.write({'state': 'published', 'publish_date': note.publish_date or fields.Datetime.now()})

    def action_unpublish(self):
        self.write({'state': 'draft'})

    @api.model
    def _bxi_student_domain(self, enrollment):
        """Published notes a student in `enrollment` (op.student.course) sees."""
        return [('state', '=', 'published'), ('course_id', '=', enrollment.course_id.id),
                '|', ('batch_ids', '=', False), ('batch_ids', 'in', enrollment.batch_id.ids)]


class BxiStudyNoteComment(models.Model):
    _name = 'bxi.study.note.comment'
    _description = 'Study Note Comment'
    _order = 'create_date desc, id desc'

    note_id = fields.Many2one('bxi.study.note', required=True, index=True, ondelete='cascade')
    author_id = fields.Many2one('res.users', string='Author', required=True, index=True,
                                default=lambda self: self.env.user)
    body = fields.Text(required=True)
    parent_id = fields.Many2one('bxi.study.note.comment', string='Reply To', index=True, ondelete='cascade')
    reply_ids = fields.One2many('bxi.study.note.comment', 'parent_id', string='Replies')
    like_user_ids = fields.Many2many('res.users', 'bxi_study_note_comment_like_rel', 'comment_id', 'user_id',
                                     string='Liked By')
    hidden = fields.Boolean(help='Hidden by a teacher: no longer shown in the app.')
