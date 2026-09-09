# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

UPCOMING_WINDOW_DAYS = 30
CARD_LIMIT = 50


class AcademicDashboard(models.AbstractModel):
    """Server-side aggregation for the Academic Management Dashboard client
    action. Every number here is a live query against the models the other
    academic modules already maintain - nothing is cached or precomputed.
    """
    _name = 'bxi.academic.dashboard'
    _description = 'Academic Management Dashboard'

    @api.model
    def get_dashboard_data(self):
        return {
            'kpis': self._get_kpis(),
            'curricula': self._get_curricula(),
            'lesson_plans': self._get_lesson_plans(),
            'calendar_events': self._get_calendar_events(),
        }

    def _get_kpis(self):
        Curriculum = self.env['bxi.curriculum'].sudo()
        PtmMeeting = self.env['bxi.ptm.meeting'].sudo()
        LessonPlan = self.env['bxi.lesson.plan'].sudo()

        now = fields.Datetime.now()
        upcoming_before = now + relativedelta(days=UPCOMING_WINDOW_DAYS)

        return {
            'total_curriculum': Curriculum.search_count([]),
            'active_curriculums': Curriculum.search_count([('locked', '=', False)]),
            'upcoming_events': PtmMeeting.search_count([
                ('start_datetime', '>=', now), ('start_datetime', '<=', upcoming_before),
            ]),
            'pending_approvals': (
                Curriculum.search_count([('approval_status', '=', 'draft')])
                + LessonPlan.search_count([('state', '=', 'pending')])
            ),
            'lesson_plans': LessonPlan.search_count([]),
        }

    def _get_curricula(self):
        Curriculum = self.env['bxi.curriculum'].sudo()
        Mapping = self.env['bxi.subject.mapping'].sudo()

        curricula = Curriculum.search([], limit=CARD_LIMIT)
        mappings = Mapping.search([('curriculum_id', 'in', curricula.ids)])
        subjects_by_curriculum = {}
        for mapping in mappings:
            subjects_by_curriculum.setdefault(mapping.curriculum_id.id, set()).add(mapping.subject_id.name)

        return [{
            'id': curriculum.id,
            'name': curriculum.name,
            'board': curriculum.board_id.name,
            'classes': curriculum.class_ids.mapped('name'),
            'subjects': sorted(subjects_by_curriculum.get(curriculum.id, [])),
            'projects': curriculum.project_ids.mapped('name'),
            'created': fields.Date.to_string(curriculum.create_date),
            'approval_status': curriculum.approval_status,
            'locked': curriculum.locked,
        } for curriculum in curricula]

    def _get_lesson_plans(self):
        LessonPlan = self.env['bxi.lesson.plan'].sudo()
        plans = LessonPlan.search([], order='start_date desc', limit=CARD_LIMIT)
        return [{
            'id': plan.id,
            'topic': plan.topic,
            'teacher': plan.teacher_id.name,
            'subject': plan.subject_id.name,
            'class': plan.class_id.name,
            'start_date': fields.Date.to_string(plan.start_date),
            'state': plan.state,
        } for plan in plans]

    def _get_calendar_events(self):
        PtmMeeting = self.env['bxi.ptm.meeting'].sudo()
        Holiday = self.env['resource.calendar.leaves'].sudo()
        now = fields.Datetime.now()

        events = [{
            'type': 'ptm',
            'title': meeting.name,
            'date': fields.Datetime.to_string(meeting.start_datetime),
            'detail': meeting.venue,
        } for meeting in PtmMeeting.search([('start_datetime', '>=', now)], order='start_datetime', limit=CARD_LIMIT)]

        events += [{
            'type': 'holiday',
            'title': holiday.name,
            'date': fields.Datetime.to_string(holiday.date_from),
            'detail': None,
        } for holiday in Holiday.search([
            ('resource_id', '=', False), ('calendar_id', '=', False), ('date_from', '>=', now),
        ], order='date_from', limit=CARD_LIMIT)]

        events.sort(key=lambda event: event['date'])
        return events[:CARD_LIMIT]
