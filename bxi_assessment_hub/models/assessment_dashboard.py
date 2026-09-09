# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

UPCOMING_WINDOW_DAYS = 7
RECENT_EXAMS_LIMIT = 10


class AssessmentDashboard(models.AbstractModel):
    """Server-side aggregation for the Assessments & Exams Dashboard client
    action. Deliberately never uses sudo(): bxi.exam / bxi.assessment.session
    / bxi.assessment.submission are all scoped by ir.rule so a teacher only
    ever sees their own exams while a Coordinator/Manager sees everything -
    the dashboard should show the same scope the rest of the app already
    enforces, not a school-wide view for every viewer.
    """
    _name = 'bxi.assessment.dashboard'
    _description = 'Assessments & Exams Dashboard'

    @api.model
    def get_dashboard_data(self):
        return {
            'kpis': self._get_kpis(),
            'alerts': self._get_alerts(),
            'recent_exams': self._get_recent_exams(),
            'performance_by_class': self._get_performance_by_class(),
        }

    def _get_kpis(self):
        Exam = self.env['bxi.exam']
        Session = self.env['bxi.assessment.session']
        Submission = self.env['bxi.assessment.submission']

        return {
            'total_exams_scheduled': Session.search_count([]),
            'assessments_defined': Exam.search_count([]),
            'evaluation_in_progress': Submission.search_count([('status', 'in', ('submitted', 'auto_graded'))]),
            'results_locked': Submission.search_count([('status', '=', 'reviewed')]),
        }

    def _get_alerts(self):
        Exam = self.env['bxi.exam']
        Session = self.env['bxi.assessment.session']
        Submission = self.env['bxi.assessment.submission']
        today = fields.Date.context_today(self)

        pending = Submission.search([('status', '=', 'submitted')])
        pending_subjects = sorted(set(pending.mapped('exam_id.subject_id.name')) - {False})

        upcoming = Session.search([
            ('state', '=', 'scheduled'),
            ('exam_date', '>=', today),
            ('exam_date', '<=', today + relativedelta(days=UPCOMING_WINDOW_DAYS)),
        ])
        upcoming_classes = sorted(set(upcoming.mapped('class_id.name')) - {False})

        unlinked = Exam.search_count([('curriculum_id', '=', False)])

        return {
            'pending_evaluations': {'count': len(pending), 'subjects': pending_subjects},
            'upcoming_exams': {'count': len(upcoming), 'classes': upcoming_classes},
            'unlinked_exams': {'count': unlinked},
        }

    def _get_recent_exams(self):
        Session = self.env['bxi.assessment.session']
        today = fields.Date.context_today(self)
        sessions = Session.search([('state', '!=', 'cancelled')], order='exam_date desc', limit=RECENT_EXAMS_LIMIT)

        cards = []
        for session in sessions:
            if session.exam_date and session.exam_date >= today:
                status = 'scheduled'
            elif session.submission_ids and any(s.status != 'reviewed' for s in session.submission_ids):
                status = 'evaluating'
            else:
                status = 'completed'
            cards.append({
                'id': session.id,
                'exam_name': session.exam_id.name,
                'class': session.class_id.name,
                'subject': session.exam_id.subject_id.name,
                'date': fields.Date.to_string(session.exam_date),
                'status': status,
            })
        return cards

    def _get_performance_by_class(self):
        Submission = self.env['bxi.assessment.submission']
        reviewed = Submission.search([('status', '=', 'reviewed'), ('max_score', '>', 0)])

        totals = {}
        for submission in reviewed:
            class_name = submission.session_id.class_id.name
            totals.setdefault(class_name, []).append(submission.total_score / submission.max_score * 10.0)

        labels = sorted(totals.keys())
        values = [round(sum(totals[label]) / len(totals[label]), 2) for label in labels]
        return {'labels': labels, 'values': values}
