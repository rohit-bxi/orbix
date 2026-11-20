# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The student community (the dashboard's "Student Community"): students
post to their own section only; their teachers and academic coordinators
can hide posts and replies, and a post reported by enough classmates is
hidden until a teacher reviews it. No private messages between students."""
from odoo import api, fields, models

KINDS = [('discussion', 'Discussion'), ('notes', 'Shared Notes'), ('question', 'Question')]
AUTO_HIDE_REPORTS = 3


class BxiCommunityPost(models.Model):
    _name = 'bxi.community.post'
    _description = 'Student Community Post'
    _order = 'create_date desc, id desc'

    student_id = fields.Many2one('op.student', string='Student', required=True, index=True)
    author_id = fields.Many2one('res.users', string='Author', required=True, default=lambda self: self.env.user)
    batch_id = fields.Many2one('op.batch', string='Section', required=True, index=True,
                               help='Only this section (and its teachers) sees the post.')
    kind = fields.Selection(KINDS, default='discussion', required=True)
    title = fields.Char(required=True)
    body = fields.Text()
    attachment_ids = fields.Many2many(
        'ir.attachment', 'bxi_community_post_attachment_rel', 'post_id', 'attachment_id', string='Attachments')
    like_user_ids = fields.Many2many('res.users', 'bxi_community_post_like_rel', 'post_id', 'user_id',
                                     string='Liked By')
    reply_ids = fields.One2many('bxi.community.reply', 'post_id', string='Replies')
    report_ids = fields.One2many('bxi.community.report', 'post_id', string='Reports')
    report_count = fields.Integer(compute='_compute_report_count', store=True)
    state = fields.Selection([('visible', 'Visible'), ('hidden', 'Hidden')], default='visible', required=True,
                             index=True)
    hidden_reason = fields.Char()
    hidden_by_id = fields.Many2one('res.users', string='Hidden By')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('report_ids')
    def _compute_report_count(self):
        for post in self:
            post.report_count = len(post.report_ids)

    def _bxi_report(self, user, reason):
        """Report the post once per user; enough reports hide it for review."""
        self.ensure_one()
        Report = self.env['bxi.community.report'].sudo()
        if not Report.search_count([('post_id', '=', self.id), ('reporter_id', '=', user.id)], limit=1):
            Report.create({'post_id': self.id, 'reporter_id': user.id, 'reason': reason or False})
        if self.state == 'visible' and len(self.report_ids) >= AUTO_HIDE_REPORTS:
            self.write({'state': 'hidden', 'hidden_reason': 'Reported by %s students' % len(self.report_ids)})

    def action_hide(self):
        self.write({'state': 'hidden', 'hidden_by_id': self.env.uid})

    def action_unhide(self):
        self.write({'state': 'visible', 'hidden_reason': False, 'hidden_by_id': False})
        self.report_ids.unlink()


class BxiCommunityReply(models.Model):
    _name = 'bxi.community.reply'
    _description = 'Student Community Reply'
    _order = 'create_date, id'

    post_id = fields.Many2one('bxi.community.post', required=True, index=True, ondelete='cascade')
    author_id = fields.Many2one('res.users', string='Author', required=True, default=lambda self: self.env.user)
    student_id = fields.Many2one('op.student', string='Student')
    body = fields.Text(required=True)
    state = fields.Selection([('visible', 'Visible'), ('hidden', 'Hidden')], default='visible', required=True)


class BxiCommunityReport(models.Model):
    _name = 'bxi.community.report'
    _description = 'Student Community Report'
    _order = 'create_date desc, id desc'

    post_id = fields.Many2one('bxi.community.post', required=True, index=True, ondelete='cascade')
    reporter_id = fields.Many2one('res.users', string='Reported By', required=True)
    reason = fields.Char()

    _unique_post_reporter = models.Constraint('unique(post_id, reporter_id)', 'Already reported.')
