# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportTeacher(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course, cls.batch = cls._create_class('TCH')
        cls.other_course, cls.other_batch = cls._create_class('TCHO')
        cls.subject = cls.env['op.subject'].create({'name': 'Tch Science', 'code': 'TCHSCI'})
        cls.teacher_user = mail_new_test_user(
            cls.env, login='tch_teacher', groups='base.group_user,openeducat_core.group_op_faculty',
            password='TeacherPass1!')
        cls.approver_user = mail_new_test_user(
            cls.env, login='tch_approver', groups='base.group_user,hr_holidays.group_hr_holidays_user',
            password='ApproverPass1!')
        cls.parent_user = mail_new_test_user(
            cls.env, login='tch_parent', groups='base.group_portal', password='ParentPass1!')
        cls.faculty = cls._create_faculty(cls.teacher_user, first_name='Tch')
        cls.faculty.emp_id = cls.env['hr.employee'].create({'name': 'Tch Teacher', 'user_id': cls.teacher_user.id})
        cls.env['bxi.timetable.line'].create({
            'timetable_id': cls.env['bxi.timetable'].create({'course_id': cls.course.id, 'batch_id': cls.batch.id}).id,
            'day': 'monday', 'subject_id': cls.subject.id, 'teacher_id': cls.faculty.id,
            'timing_id': cls.env['op.timing'].create({
                'name': 'Tch P1', 'hour': '9', 'minute': '00', 'am_pm': 'am', 'duration': 1.0}).id,
        })
        cls.students = cls.env['op.student']
        for i in range(3):
            student = cls._create_student(f'TCH-00{i}', first_name=f'Pupil{i}', last_name='Tch')
            cls._enroll(student, cls.course, cls.batch)
            cls.students |= student
        cls.outsider = cls._create_student('TCH-099', first_name='Out', last_name='Sider')
        cls._enroll(cls.outsider, cls.other_course, cls.other_batch)
        cls._create_parent(cls.parent_user, cls.students[0])

    def _teacher(self):
        return self._headers('tch_teacher', 'TeacherPass1!')

    def _period_today(self):
        start = fields.Datetime.now().replace(minute=0, second=0, microsecond=0)
        # A generated-style period: no student_ids, roster comes from the section.
        return self.env['op.session'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id, 'subject_id': self.subject.id,
            'faculty_id': self.faculty.id, 'start_datetime': start, 'end_datetime': start + timedelta(minutes=45),
        })

    # -- my day / classes --------------------------------------------------------

    def test_classes_and_roster(self):
        classes = self.url_open('/api/v1/teacher/classes', headers=self._teacher()).json()['data']['classes']
        self.assertEqual([c['section']['id'] for c in classes], self.batch.ids)
        self.assertEqual(classes[0]['student_count'], 3)
        roster = self.url_open(f'/api/v1/teacher/classes/{self.batch.id}/students', headers=self._teacher()).json()
        self.assertEqual({s['id'] for s in roster['data']['students']}, set(self.students.ids))
        self.assertEqual(self.url_open(f'/api/v1/teacher/classes/{self.other_batch.id}/students',
                                       headers=self._teacher()).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/teacher/classes', headers=self._headers(
            'tch_parent', 'ParentPass1!')).json()['error']['code'], 'not_a_teacher')

    def test_today_and_bulk_mark(self):
        period = self._period_today()
        if period.session_date != fields.Date.context_today(period):
            return  # running across UTC midnight
        today = self.url_open('/api/v1/teacher/today', headers=self._teacher()).json()['data']['periods']
        self.assertEqual(today[0]['id'], period.id)
        self.assertEqual(today[0]['attendance_marked'], 0)

        outsider = self.url_open(f'/api/v1/attendance/sessions/{period.id}/bulk-mark', headers=self._teacher(), json={
            'marks': [{'student_id': self.outsider.id, 'status': 'present'}]})
        self.assertEqual(outsider.json()['error']['code'], 'not_on_roster')
        self.assertFalse(self.env['hr.attendance'].search_count([('session_id', '=', period.id)]),
                         'A rejected batch must save nothing.')

        marks = [{'student_id': s.id, 'status': 'present'} for s in self.students[1:]]
        marks.append({'student_id': self.students[0].id, 'status': 'absent', 'remark': 'Sick'})
        resp = self.url_open(f'/api/v1/attendance/sessions/{period.id}/bulk-mark', headers=self._teacher(),
                             json={'marks': marks})
        self.assertEqual(resp.status_code, 200, resp.text)
        statuses = {r['student_id']: r['status'] for r in resp.json()['data']['roster']}
        self.assertEqual(statuses[self.students[0].id], 'absent')
        # Re-marking updates in place instead of duplicating.
        self.url_open(f'/api/v1/attendance/sessions/{period.id}/bulk-mark', headers=self._teacher(),
                      json={'marks': [{'student_id': self.students[0].id, 'status': 'late'}]})
        self.assertEqual(self.env['hr.attendance'].search_count([('session_id', '=', period.id)]), 3)
        today = self.url_open('/api/v1/teacher/today', headers=self._teacher()).json()['data']['periods']
        self.assertTrue(today[0]['attendance_complete'])

        summary = self.url_open(f'/api/v1/attendance/students/{self.students[0].id}/summary',
                                headers=self._teacher()).json()['data']
        self.assertEqual(summary['summary']['late'], 1)
        parent_view = self.url_open(f'/api/v1/parent/attendance?student_id={self.students[0].id}',
                                    headers=self._headers('tch_parent', 'ParentPass1!')).json()['data']
        self.assertEqual(parent_view['summary']['late'], 1, 'Parents see what the teacher marked.')
        self.assertEqual(self.url_open(f'/api/v1/attendance/students/{self.outsider.id}/summary',
                                       headers=self._teacher()).status_code, 403)

    # -- question authoring ------------------------------------------------------

    def test_question_authoring(self):
        exam_id = self.url_open('/api/v1/assessments/exams', headers=self._teacher(), json={
            'name': 'Tch Quiz', 'class_id': self.course.id, 'subject_id': self.subject.id,
        }).json()['data']['id']
        bad = self.url_open(f'/api/v1/assessments/exams/{exam_id}/questions', headers=self._teacher(), json={
            'question_text': 'x', 'question_type': 'essay'})
        self.assertEqual(bad.json()['error']['code'], 'invalid_question_type')
        mcq = self.url_open(f'/api/v1/assessments/exams/{exam_id}/questions', headers=self._teacher(), json={
            'question_type': 'mcq', 'question_text': 'H2O is?', 'marks': 2,
            'options': [{'option_text': 'Water', 'is_correct': True}, {'option_text': 'Salt'}],
        })
        self.assertEqual(mcq.status_code, 201, mcq.text)
        question_id = mcq.json()['data']['id']
        self.assertEqual(len(mcq.json()['data']['options']), 2)
        updated = self.url_open(f'/api/v1/assessments/questions/{question_id}/update', headers=self._teacher(), json={
            'marks': 3, 'options': [{'option_text': 'H2O', 'is_correct': True}, {'option_text': 'CO2'},
                                    {'option_text': 'NaCl'}]})
        self.assertEqual(len(updated.json()['data']['options']), 3)
        paper = self.url_open(f'/api/v1/assessments/exams/{exam_id}/questions', headers=self._teacher()).json()
        self.assertEqual(paper['data']['exam']['total_marks'], 3)
        self.assertEqual(self.url_open(f'/api/v1/assessments/exams/{exam_id}/questions',
                                       headers=self._headers('tch_parent', 'ParentPass1!')).status_code, 403)
        self.url_open(f'/api/v1/assessments/exams/{exam_id}/publish', headers=self._teacher(), method='POST')
        locked = self.url_open(f'/api/v1/assessments/questions/{question_id}/delete', headers=self._teacher(),
                               method='POST')
        self.assertEqual(locked.json()['error']['code'], 'exam_published')

    # -- leave ---------------------------------------------------------------------

    def test_leave_request_and_approval(self):
        leave_type = self.env['hr.leave.type'].create({
            'name': 'Tch Casual', 'requires_allocation': False, 'request_unit': 'day',
            'leave_validation_type': 'hr', 'company_id': self.env.company.id,
        })
        types = self.url_open('/api/v1/leaves/types', headers=self._teacher()).json()['data']['types']
        self.assertIn(leave_type.id, [t['id'] for t in types])
        monday = fields.Date.today() + timedelta(days=(7 - fields.Date.today().weekday()))
        create = self.url_open('/api/v1/leaves', headers=self._teacher(), json={
            'type_id': leave_type.id, 'date_from': fields.Date.to_string(monday),
            'date_to': fields.Date.to_string(monday), 'description': 'Family function'})
        self.assertEqual(create.status_code, 201, create.text)
        leave_id = create.json()['data']['id']
        mine = self.url_open('/api/v1/leaves/my', headers=self._teacher()).json()['data']['leaves']
        self.assertEqual([l['id'] for l in mine], [leave_id])

        self.assertEqual(self.url_open(f'/api/v1/leaves/{leave_id}/approve', headers=self._teacher(),
                                       method='POST').status_code, 400)
        approver = self._headers('tch_approver', 'ApproverPass1!')
        queue = self.url_open('/api/v1/leaves/to-approve', headers=approver).json()['data']['leaves']
        self.assertIn(leave_id, [l['id'] for l in queue])
        approved = self.url_open(f'/api/v1/leaves/{leave_id}/approve', headers=approver, method='POST')
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()['data']['state'], 'validate')

    # -- activity log ------------------------------------------------------------

    def test_activity_log(self):
        activity_type = self.env['op.activity.type'].create({'name': 'Tch Merit'})
        logged = self.url_open('/api/v1/activities', headers=self._teacher(), json={
            'student_id': self.students[0].id, 'type_id': activity_type.id, 'description': 'Helped a classmate'})
        self.assertEqual(logged.status_code, 201, logged.text)
        self.assertEqual(self.url_open('/api/v1/activities', headers=self._teacher(), json={
            'student_id': self.outsider.id, 'description': 'x'}).status_code, 403)
        listing = self.url_open(f'/api/v1/students/{self.students[0].id}/activities',
                                headers=self._headers('tch_parent', 'ParentPass1!')).json()['data']['activities']
        self.assertEqual(listing[0]['description'], 'Helped a classmate')
