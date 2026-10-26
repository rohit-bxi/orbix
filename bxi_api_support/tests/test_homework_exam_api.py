# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportHomeworkExam(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course, cls.batch = cls._create_class('HWX')
        cls.other_course, cls.other_batch = cls._create_class('HWY')
        cls.subject = cls.env['op.subject'].create({'name': 'HW Maths', 'code': 'HWMATH'})
        cls.student_user = mail_new_test_user(
            cls.env, login='hw_student', groups='base.group_portal', password='StudentPass1!')
        cls.parent_user = mail_new_test_user(
            cls.env, login='hw_parent', groups='base.group_portal', password='ParentPass1!')
        cls.other_parent_user = mail_new_test_user(
            cls.env, login='hw_other_parent', groups='base.group_portal', password='OtherPass1!')
        cls.teacher_user = mail_new_test_user(
            cls.env, login='hw_teacher', groups='base.group_user,openeducat_core.group_op_faculty',
            password='TeacherPass1!')
        cls.exam_staff_user = mail_new_test_user(
            cls.env, login='hw_exam_staff', groups='base.group_user,openeducat_exam.group_op_exam_user',
            password='ExamPass1!')
        cls.student = cls._create_student('HW-001', first_name='Hana', last_name='Writer', user=cls.student_user)
        cls._enroll(cls.student, cls.course, cls.batch)
        cls.other_student = cls._create_student('HW-002', first_name='Omar', last_name='Elsewhere')
        cls._enroll(cls.other_student, cls.other_course, cls.other_batch)
        cls._create_parent(cls.parent_user, cls.student)
        cls._create_parent(cls.other_parent_user, cls.other_student)
        cls.faculty = cls._create_faculty(cls.teacher_user, first_name='HW')
        cls.batch.class_teacher_id = cls.faculty
        cls.assignment_type = cls.env['grading.assignment.type'].create({'name': 'Homework', 'code': 'HWT'})

    def _teacher(self):
        return self._headers('hw_teacher', 'TeacherPass1!')

    def _create_homework(self, **overrides):
        payload = dict({
            'name': 'Fractions worksheet', 'description': 'Do page 12', 'batch_id': self.batch.id,
            'subject_id': self.subject.id, 'assignment_type_id': self.assignment_type.id, 'marks': 10,
            'submission_date': fields.Datetime.to_string(fields.Datetime.now() + timedelta(days=3)),
        }, **overrides)
        return self.url_open('/api/v1/assignments', headers=self._teacher(), json=payload)

    # -- homework -------------------------------------------------------------

    def test_teacher_cannot_create_for_a_section_they_dont_teach(self):
        resp = self._create_homework(batch_id=self.other_batch.id)
        self.assertEqual(resp.status_code, 403)

    def test_homework_lifecycle_family_view_submit_and_review(self):
        create = self._create_homework()
        self.assertEqual(create.status_code, 201, create.text)
        assignment_id = create.json()['data']['id']

        # Draft homework is invisible to the family.
        parent = self._headers('hw_parent', 'ParentPass1!')
        listing = self.url_open(f'/api/v1/assignments?student_id={self.student.id}', headers=parent).json()
        self.assertEqual(listing['data']['assignments'], [])

        publish = self.url_open(f'/api/v1/assignments/{assignment_id}/publish', headers=self._teacher(), method='POST')
        self.assertEqual(publish.status_code, 200)
        self.assertEqual(
            len(self.env['bxi.notification'].search([('user_id', '=', self.parent_user.id), ('category', '=', 'homework')])), 1)

        pending = self.url_open(f'/api/v1/assignments?student_id={self.student.id}&state=pending', headers=parent).json()
        self.assertEqual([a['id'] for a in pending['data']['assignments']], [assignment_id])
        self.assertIsNone(pending['data']['assignments'][0]['my_submission'])

        # Parents can read but not submit; another family can't even read.
        self.assertEqual(self.url_open(
            f'/api/v1/assignments/{assignment_id}/submit', headers=parent, json={'description': 'x'}).status_code, 403)
        self.assertEqual(self.url_open(
            f'/api/v1/assignments/{assignment_id}?student_id={self.student.id}',
            headers=self._headers('hw_other_parent', 'OtherPass1!')).status_code, 403)

        student = self._headers('hw_student', 'StudentPass1!')
        submit = self.url_open(f'/api/v1/assignments/{assignment_id}/submit', headers=student, json={
            'description': 'Done',
            'attachments': [{'name': 'work.txt', 'data': base64.b64encode(b'answers').decode(), 'mimetype': 'text/plain'}],
        })
        self.assertEqual(submit.status_code, 201, submit.text)
        submission = submit.json()['data']
        self.assertEqual(submission['state'], 'submit')
        self.assertEqual(len(submission['attachments']), 1)
        again = self.url_open(f'/api/v1/assignments/{assignment_id}/submit', headers=student, json={'description': 'x'})
        self.assertEqual(again.json()['error']['code'], 'already_submitted')

        download = self.url_open(
            f"/api/v1/assignments/attachments/{submission['attachments'][0]['id']}", headers=parent)
        self.assertEqual(download.content, b'answers')

        submissions = self.url_open(f'/api/v1/assignments/{assignment_id}/submissions', headers=self._teacher()).json()
        self.assertEqual(submissions['data']['submissions'][0]['state'], 'submit')
        too_many = self.url_open(
            f"/api/v1/assignments/submissions/{submission['id']}/accept", headers=self._teacher(), json={'marks': 50})
        self.assertEqual(too_many.status_code, 400)
        accept = self.url_open(
            f"/api/v1/assignments/submissions/{submission['id']}/accept", headers=self._teacher(), json={'marks': 8})
        self.assertEqual(accept.status_code, 200)
        self.assertEqual(accept.json()['data']['marks'], 8)

        detail = self.url_open(f'/api/v1/assignments/{assignment_id}?student_id={self.student.id}', headers=parent).json()
        self.assertEqual(detail['data']['my_submission']['state'], 'accept')

    def test_request_changes_allows_resubmission(self):
        assignment_id = self._create_homework().json()['data']['id']
        self.url_open(f'/api/v1/assignments/{assignment_id}/publish', headers=self._teacher(), method='POST')
        student = self._headers('hw_student', 'StudentPass1!')
        sub_id = self.url_open(f'/api/v1/assignments/{assignment_id}/submit', headers=student,
                               json={'description': 'v1'}).json()['data']['id']
        self.url_open(f'/api/v1/assignments/submissions/{sub_id}/request-changes', headers=self._teacher(),
                      json={'note': 'Show working'})
        resubmit = self.url_open(f'/api/v1/assignments/{assignment_id}/submit', headers=student, json={'description': 'v2'})
        self.assertEqual(resubmit.status_code, 201)
        self.assertEqual(resubmit.json()['data']['description'], 'v2')

    # -- exams ----------------------------------------------------------------

    def _exam_session(self, state='schedule'):
        exam_type = self.env['op.exam.type'].create({'name': 'Mid term', 'code': f'MT{state}'})
        today = fields.Date.today()
        session = self.env['op.exam.session'].create({
            'name': f'Mid term {state}', 'course_id': self.course.id, 'batch_id': self.batch.id,
            'exam_code': f'HWES-{state}', 'start_date': today, 'end_date': today + timedelta(days=5),
            'exam_type': exam_type.id, 'state': state,
        })
        start = fields.Datetime.now() + timedelta(hours=2)
        exam = self.env['op.exam'].create({
            'session_id': session.id, 'subject_id': self.subject.id, 'exam_code': f'HWEX-{state}',
            'start_time': start, 'end_time': start + timedelta(hours=1), 'name': 'Maths paper',
            'total_marks': 50, 'min_marks': 20,
        })
        self.env['op.exam.attendees'].create({'exam_id': exam.id, 'student_id': self.student.id})
        return session, exam

    def test_date_sheet_only_shows_own_class(self):
        session, _exam = self._exam_session()
        parent = self._headers('hw_parent', 'ParentPass1!')
        sessions = self.url_open(f'/api/v1/exams/schedule?student_id={self.student.id}', headers=parent).json()
        self.assertEqual([s['id'] for s in sessions['data']['sessions']], session.ids)
        other = self.url_open(f'/api/v1/exams/schedule?student_id={self.other_student.id}', headers=parent)
        self.assertEqual(other.status_code, 403)

    def test_hall_ticket_is_rendered_for_one_student(self):
        session, _exam = self._exam_session()
        resp = self.url_open(
            f'/api/v1/exams/hall-ticket?student_id={self.student.id}&session_id={session.id}',
            headers=self._headers('hw_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 200)
        # Test mode renders the report as HTML instead of PDF - enough to
        # check which students made it into the document.
        self.assertIn(self.student.name, resp.text)
        self.assertNotIn(self.other_student.name, resp.text)

    def test_marks_entry_validates_then_saves(self):
        session, exam = self._exam_session()
        staff = self._headers('hw_exam_staff', 'ExamPass1!')
        early = self.url_open(f'/api/v1/exams/{exam.id}/marks', headers=staff,
                              json={'marks': [{'student_id': self.student.id, 'marks': 30}]})
        self.assertEqual(early.json()['error']['code'], 'invalid_transition')
        self.url_open(f'/api/v1/exams/{exam.id}/schedule', headers=staff, method='POST')
        self.url_open(f'/api/v1/exams/{exam.id}/held', headers=staff, method='POST')
        bad = self.url_open(f'/api/v1/exams/{exam.id}/marks', headers=staff,
                            json={'marks': [{'student_id': self.student.id, 'marks': 99}]})
        self.assertEqual(bad.json()['error']['code'], 'invalid_marks')
        outsider = self.url_open(f'/api/v1/exams/{exam.id}/marks', headers=staff,
                                 json={'marks': [{'student_id': self.other_student.id, 'marks': 10}]})
        self.assertEqual(outsider.json()['error']['code'], 'not_attendee')
        ok = self.url_open(f'/api/v1/exams/{exam.id}/marks', headers=self._teacher(),
                           json={'marks': [{'student_id': self.student.id, 'marks': 42}]})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()['data']['attendees'][0]['marks'], 42)
        family = self.url_open(f'/api/v1/exams/{exam.id}/marks', headers=self._headers('hw_parent', 'ParentPass1!'),
                               json={'marks': [{'student_id': self.student.id, 'marks': 50}]})
        self.assertEqual(family.status_code, 403)

    def test_generate_and_publish_results_notifies_family(self):
        session, exam = self._exam_session(state='held')
        exam.attendees_line.marks = 40
        exam.state = 'done'  # a result template requires every paper done
        template = self.env['op.result.template'].create({'exam_session_id': session.id, 'name': 'Mid term results'})
        staff = self._headers('hw_exam_staff', 'ExamPass1!')
        generated = self.url_open(f'/api/v1/exams/result-templates/{template.id}/generate', headers=staff, method='POST')
        self.assertEqual(generated.status_code, 201, generated.text)
        register_id = generated.json()['data']['marksheet_register_id']
        publish = self.url_open(f'/api/v1/exams/marksheets/{register_id}/publish', headers=staff, method='POST')
        self.assertEqual(publish.status_code, 200)
        self.assertTrue(self.env['bxi.notification'].search_count(
            [('user_id', '=', self.parent_user.id), ('category', '=', 'result')]))
        line = self.env['op.marksheet.line'].search([('marksheet_reg_id', '=', register_id)])
        card = self.url_open(f'/api/v1/exams/report-card/{line.id}', headers=self._headers('hw_parent', 'ParentPass1!'))
        self.assertEqual(card.status_code, 200)
