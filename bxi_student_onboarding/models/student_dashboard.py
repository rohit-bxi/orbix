# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from collections import Counter

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

MONTH_WINDOW = 6
STUDENT_LIST_LIMIT = 10
ONBOARDING_LIST_LIMIT = 10
COURSE_WISE_LIMIT = 8
RECENT_ACTIVITY_LIMIT = 8

ENROLLMENT_STATUS_KIND = {
    'new_admission': 'info',
    'active': 'success',
    'transferred': 'warning',
    'alumni': 'success',
    'dropped': 'danger',
}
ONBOARDING_STATE_KIND = {
    'basic_info': 'info',
    'academic_info': 'warning',
    'documents': 'warning',
    'done': 'success',
}

GENDER_LABELS = {'m': 'Male', 'f': 'Female', 'o': 'Other'}


class BxiStudentDashboard(models.AbstractModel):
    """Server-side aggregation for the Student Information System Dashboard
    client action. Every number here is a live query against op.student /
    op.student.course / bxi.student.onboarding - nothing is cached, so the
    dashboard always matches the underlying list views.
    """
    _name = 'bxi.student.dashboard'
    _description = 'Student Information Dashboard'

    def _month_bounds(self, months_ago=0):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1) - relativedelta(months=months_ago)
        month_end = month_start + relativedelta(months=1) - relativedelta(days=1)
        return month_start, month_end

    @api.model
    def get_dashboard_data(self):
        Student = self.env['op.student'].sudo()
        students = Student.search([('active', '=', True)])
        Onboarding = self.env['bxi.student.onboarding'].sudo()
        onboardings = Onboarding.search([])
        return {
            'kpis': self._get_kpis(students, onboardings),
            'student_list': self._get_student_list(Student),
            'charts': {
                'enrollment_status_distribution': self._get_enrollment_status_distribution(students),
                'gender_distribution': self._get_gender_distribution(students),
                'course_wise_distribution': self._get_course_wise_distribution(),
                'monthly_admission_trend': self._get_monthly_admission_trend(students),
            },
            'onboarding_pipeline': self._get_onboarding_pipeline(Onboarding),
            'stats': self._get_secondary_stats(students),
            'recent_activity': self._get_recent_activity(),
        }

    def _get_kpis(self, students, onboardings):
        month_start, _month_end = self._month_bounds(0)
        next_month_start = month_start + relativedelta(months=1)
        new_admissions_month = students.filtered(
            lambda s: s.admission_date and month_start <= s.admission_date < next_month_start)
        onboarding_in_progress = onboardings.filtered(lambda o: o.state != 'done')
        done_onboardings = onboardings.filtered(lambda o: o.state == 'done')
        return {
            'total_students': {'value': len(students)},
            'new_admissions_month': {'value': len(new_admissions_month)},
            'onboarding_in_progress': {'value': len(onboarding_in_progress)},
            'onboarding_completion_rate': {
                'value': round(len(done_onboardings) / len(onboardings) * 100.0, 1) if onboardings else 0.0,
            },
        }

    def _get_student_list(self, Student):
        records = Student.search([('active', '=', True)], order='write_date desc', limit=STUDENT_LIST_LIMIT)
        status_labels = dict(Student._fields['enrollment_status'].selection)
        return [{
            'id': s.id,
            'name': s.name or '',
            'course_batch': self._running_course_batch(s),
            'enrollment_status': s.enrollment_status,
            'enrollment_status_label': status_labels.get(s.enrollment_status, s.enrollment_status or '-'),
            'admission_date': fields.Date.to_string(s.admission_date) if s.admission_date else '',
            'gender': GENDER_LABELS.get(s.gender, s.gender or '-'),
        } for s in records]

    def _running_course_batch(self, student):
        running = student.course_detail_ids.filtered(lambda c: c.state == 'running')[:1] \
            or student.course_detail_ids[:1]
        if not running:
            return '-'
        return '%s - %s' % (running.course_id.name or '', running.batch_id.name or '')

    def _get_enrollment_status_distribution(self, students):
        Student = self.env['op.student']
        status_labels = dict(Student._fields['enrollment_status'].selection)
        counter = Counter(students.mapped('enrollment_status'))
        ordered = [key for key, _label in Student._fields['enrollment_status'].selection if key in counter]
        return {
            'labels': [status_labels.get(k, k) for k in ordered],
            'values': [counter[k] for k in ordered],
        }

    def _get_gender_distribution(self, students):
        counter = Counter(students.mapped('gender'))
        ordered = sorted(counter, key=lambda k: counter[k], reverse=True)
        return {
            'labels': [GENDER_LABELS.get(k, k or 'Unspecified') for k in ordered],
            'values': [counter[k] for k in ordered],
        }

    def _get_course_wise_distribution(self):
        StudentCourse = self.env['op.student.course'].sudo()
        lines = StudentCourse.search([('state', '=', 'running')])
        counter = Counter(line.course_id.name for line in lines if line.course_id)
        ordered = sorted(counter, key=lambda k: counter[k], reverse=True)[:COURSE_WISE_LIMIT]
        return {
            'labels': ordered,
            'values': [counter[k] for k in ordered],
        }

    def _get_monthly_admission_trend(self, students):
        labels, values = [], []
        for i in range(MONTH_WINDOW - 1, -1, -1):
            month_start, month_end = self._month_bounds(i)
            month_records = students.filtered(
                lambda s: s.admission_date and month_start <= s.admission_date <= month_end)
            labels.append(month_start.strftime('%b'))
            values.append(len(month_records))
        return {'labels': labels, 'values': values}

    def _get_onboarding_pipeline(self, Onboarding):
        records = Onboarding.search(
            [('state', '!=', 'done')], order='write_date desc', limit=ONBOARDING_LIST_LIMIT)
        state_labels = dict(Onboarding._fields['state'].selection)
        return [{
            'id': o.id,
            'full_name': o.full_name or '',
            'state': o.state,
            'state_label': state_labels.get(o.state, o.state),
            'course': o.course_id.name or '-',
            'admission_number': o.admission_number or '-',
        } for o in records]

    def _get_secondary_stats(self, students):
        students_with_medical_alert = len(students.filtered(lambda s: s.is_allergy))
        students_without_parent = len(students.filtered(lambda s: not s.parent_ids))
        students_missing_blood_group = len(students.filtered(lambda s: not s.blood_group))
        return {
            'students_with_medical_alert': students_with_medical_alert,
            'students_without_parent': students_without_parent,
            'students_missing_blood_group': students_missing_blood_group,
        }

    def _get_recent_activity(self):
        activities = []

        Student = self.env['op.student'].sudo()
        status_labels = dict(Student._fields['enrollment_status'].selection)
        for student in Student.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': '%s - %s' % (
                    student.name or '', status_labels.get(student.enrollment_status, student.enrollment_status)),
                'date': fields.Datetime.to_string(student.write_date),
                'kind': ENROLLMENT_STATUS_KIND.get(student.enrollment_status, 'info'),
            })

        Onboarding = self.env['bxi.student.onboarding'].sudo()
        onboarding_labels = dict(Onboarding._fields['state'].selection)
        for onboarding in Onboarding.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': 'Onboarding: %s - %s' % (
                    onboarding.full_name or '', onboarding_labels.get(onboarding.state, onboarding.state)),
                'date': fields.Datetime.to_string(onboarding.write_date),
                'kind': ONBOARDING_STATE_KIND.get(onboarding.state, 'info'),
            })

        activities.sort(key=lambda a: a['date'], reverse=True)
        return activities[:RECENT_ACTIVITY_LIMIT]
