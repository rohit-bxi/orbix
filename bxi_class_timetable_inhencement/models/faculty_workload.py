# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import api, fields, models


class OpFacultyWorkload(models.Model):
    _inherit = 'op.faculty'

    max_weekly_periods = fields.Integer(default=30)
    # Inverse of bxi.timetable.line.teacher_id, kept only so
    # _compute_weekly_period_count has a real field to declare in
    # @api.depends - a plain search_count() inside the compute has no
    # dependency the ORM can track, so the cached value would never be
    # refreshed after the first read (e.g. when a period is added or
    # removed later in the same transaction).
    line_ids = fields.One2many('bxi.timetable.line', 'teacher_id')
    weekly_period_count = fields.Integer(compute='_compute_weekly_period_count')
    workload_status = fields.Selection([
        ('normal', 'Normal'),
        ('near_limit', 'Near Limit'),
        ('over_limit', 'Over Limit'),
    ], compute='_compute_weekly_period_count')
    available_monday = fields.Boolean(default=True)
    available_tuesday = fields.Boolean(default=True)
    available_wednesday = fields.Boolean(default=True)
    available_thursday = fields.Boolean(default=True)
    available_friday = fields.Boolean(default=True)
    available_saturday = fields.Boolean(default=True)

    def is_available_on(self, day):
        """Whether this teacher is marked available on `day` (a
        bxi.timetable.line day-selection value, e.g. 'monday')."""
        self.ensure_one()
        return bool(getattr(self, 'available_%s' % day, True))

    @api.depends('line_ids', 'max_weekly_periods')
    def _compute_weekly_period_count(self):
        for faculty in self:
            count = len(faculty.line_ids)
            faculty.weekly_period_count = count
            ratio = count / (faculty.max_weekly_periods or 1)
            # >= (not >) for over_limit: add_period_wizard already blocks adding
            # a period once count reaches max (count + 1 > max), so a teacher
            # sitting exactly at their cap is "over" what they can still take,
            # not merely "normal". A 0.9 near_limit threshold was also
            # effectively unreachable for small max_weekly_periods values
            # (e.g. max=2 can only ever be 0%, 50% or 100% booked, so it would
            # jump straight from 'normal' to 'over_limit'); 0.5 gives a
            # meaningful early warning across realistic caps.
            if ratio >= 1:
                faculty.workload_status = 'over_limit'
            elif ratio >= 0.5:
                faculty.workload_status = 'near_limit'
            else:
                faculty.workload_status = 'normal'
