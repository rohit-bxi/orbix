# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The digital library's reading side: how far a student is in a book
("Continue Reading 65%"), their reading list, and the days they read
(for the reading streak)."""
from datetime import timedelta

from odoo import api, fields, models


class BxiReadingProgress(models.Model):
    _name = 'bxi.reading.progress'
    _description = 'Reading Progress'
    _order = 'last_read desc, id desc'

    student_id = fields.Many2one('op.student', required=True, index=True, ondelete='cascade')
    media_id = fields.Many2one('op.media', string='Book', required=True, index=True, ondelete='cascade')
    percent = fields.Float('Progress (%)', default=0.0)
    current_page = fields.Integer()
    total_pages = fields.Integer()
    chapter = fields.Char(help='Where the reader is, e.g. "Chapter 5: Quadratic Equations".')
    last_read = fields.Datetime(default=fields.Datetime.now, index=True)
    completed = fields.Boolean(compute='_compute_completed', store=True)

    _unique_student_media = models.Constraint('unique(student_id, media_id)',
                                              'A student has one reading position per book.')

    @api.depends('percent')
    def _compute_completed(self):
        for progress in self:
            progress.completed = progress.percent >= 100


class BxiReadingListItem(models.Model):
    _name = 'bxi.reading.list.item'
    _description = 'Reading List Item'
    _order = 'create_date desc, id desc'

    student_id = fields.Many2one('op.student', required=True, index=True, ondelete='cascade')
    media_id = fields.Many2one('op.media', string='Book', required=True, index=True, ondelete='cascade')

    _unique_student_media = models.Constraint('unique(student_id, media_id)', 'This book is already on the list.')


class BxiReadingDay(models.Model):
    _name = 'bxi.reading.day'
    _description = 'Reading Day'
    _order = 'day desc'

    student_id = fields.Many2one('op.student', required=True, index=True, ondelete='cascade')
    day = fields.Date(required=True, index=True)

    _unique_student_day = models.Constraint('unique(student_id, day)', 'One row per student and day.')

    @api.model
    def _bxi_mark(self, student, day):
        if not self.sudo().search_count([('student_id', '=', student.id), ('day', '=', day)], limit=1):
            self.sudo().create({'student_id': student.id, 'day': day})

    @api.model
    def _bxi_streak(self, student, today):
        """Consecutive reading days ending today (or yesterday, so the
        streak survives until the student reads today)."""
        days = set(self.sudo().search([('student_id', '=', student.id),
                                       ('day', '>=', today - timedelta(days=366))]).mapped('day'))
        day = today if today in days else today - timedelta(days=1)
        streak = 0
        while day in days:
            streak += 1
            day -= timedelta(days=1)
        return streak
