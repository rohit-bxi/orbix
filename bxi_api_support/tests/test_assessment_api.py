# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64
import io
from unittest.mock import patch

from openpyxl import Workbook

from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportAssessment(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.teacher_user = mail_new_test_user(
            cls.env, login='assess_api_teacher', groups='base.group_user,openeducat_core.group_op_faculty',
            password='TeacherPass1!')
        cls.other_teacher_user = mail_new_test_user(
            cls.env, login='assess_api_other_teacher', groups='base.group_user,openeducat_core.group_op_faculty',
            password='OtherTeacherPass1!')
        cls.coordinator_user = mail_new_test_user(
            cls.env, login='assess_api_coordinator',
            groups='base.group_user,bxi_academic_management.group_academic_coordinator',
            password='CoordPass1!')
        cls.course = cls.env['op.course'].create({'name': 'Assess API Course', 'code': 'ASS-C1'})
        cls.subject = cls.env['op.subject'].create({'name': 'Assess API Subject', 'code': 'ASS-S1'})
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Assess', 'last_name': 'Teacher', 'gender': 'male',
            'birth_date': '1985-01-01', 'user_id': cls.teacher_user.id,
        })
        cls.other_faculty = cls.env['op.faculty'].create({
            'first_name': 'Other', 'last_name': 'Teacher', 'gender': 'female',
            'birth_date': '1986-01-01', 'user_id': cls.other_teacher_user.id,
        })
        cls.student = cls._create_student('ASSAPI-001')

    def _teacher_headers(self):
        return self._headers('assess_api_teacher', 'TeacherPass1!')

    def _create_exam(self):
        resp = self.url_open('/api/v1/assessments/exams', headers=self._teacher_headers(), json={
            'name': 'API Exam 1', 'class_id': self.course.id, 'subject_id': self.subject.id,
        })
        return resp.json()['data']

    def test_exams_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/assessments/exams').status_code, 401)

    def test_teacher_can_create_exam(self):
        exam = self._create_exam()
        self.assertEqual(exam['state'], 'draft')
        self.assertEqual(exam['teacher'], self.faculty.display_name)

    def test_publish_requires_questions(self):
        exam = self._create_exam()
        resp = self.url_open(
            f'/api/v1/assessments/exams/{exam["id"]}/publish', headers=self._teacher_headers(), method='POST')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_transition')

    def test_other_teacher_cannot_publish(self):
        exam = self._create_exam()
        resp = self.url_open(
            f'/api/v1/assessments/exams/{exam["id"]}/publish',
            headers=self._headers('assess_api_other_teacher', 'OtherTeacherPass1!'), method='POST')
        self.assertEqual(resp.status_code, 403)

    def test_full_exam_session_submission_grading_flow(self):
        exam = self._create_exam()
        exam_record = self.env['bxi.exam'].sudo().browse(exam['id'])
        question = self.env['bxi.exam.question'].sudo().create({
            'exam_id': exam_record.id, 'question_type': 'mcq', 'question_text': 'What is 2+2?', 'marks': 5,
        })
        correct_option = self.env['bxi.exam.question.option'].sudo().create({
            'question_id': question.id, 'option_text': '4', 'is_correct': True,
        })
        self.env['bxi.exam.question.option'].sudo().create({
            'question_id': question.id, 'option_text': '5', 'is_correct': False,
        })

        headers = self._teacher_headers()
        publish = self.url_open(f'/api/v1/assessments/exams/{exam["id"]}/publish', headers=headers, method='POST')
        self.assertEqual(publish.status_code, 200)
        self.assertEqual(publish.json()['data']['state'], 'published')

        session_resp = self.url_open('/api/v1/assessments/sessions', headers=headers, json={
            'exam_id': exam['id'], 'class_id': self.course.id, 'student_ids': [self.student.id],
        })
        self.assertEqual(session_resp.status_code, 201)
        session = session_resp.json()['data']
        self.assertEqual(session['submission_count'], 1)

        submissions = self.url_open(
            f'/api/v1/assessments/submissions?session_id={session["id"]}', headers=headers).json()['data']['submissions']
        self.assertEqual(len(submissions), 1)
        submission_id = submissions[0]['id']

        answer_resp = self.url_open(
            f'/api/v1/assessments/submissions/{submission_id}/answers', headers=headers, json={
                'answers': [{'question_id': question.id, 'selected_option_id': correct_option.id}],
            })
        self.assertEqual(answer_resp.status_code, 200)

        mark_resp = self.url_open(
            f'/api/v1/assessments/submissions/{submission_id}/mark-submitted', headers=headers, method='POST')
        self.assertEqual(mark_resp.status_code, 200)
        self.assertEqual(mark_resp.json()['data']['status'], 'submitted')

        grade_resp = self.url_open(
            f'/api/v1/assessments/submissions/{submission_id}/auto-grade', headers=headers, method='POST')
        self.assertEqual(grade_resp.status_code, 200)
        self.assertEqual(grade_resp.json()['data']['status'], 'auto_graded')
        self.assertEqual(grade_resp.json()['data']['total_score'], 5.0)

    def test_cancel_session_requires_ownership(self):
        exam = self._create_exam()
        headers = self._teacher_headers()
        session = self.url_open('/api/v1/assessments/sessions', headers=headers, json={
            'exam_id': exam['id'], 'class_id': self.course.id, 'student_ids': [self.student.id],
        }).json()['data']

        resp = self.url_open(
            f'/api/v1/assessments/sessions/{session["id"]}/cancel',
            headers=self._headers('assess_api_other_teacher', 'OtherTeacherPass1!'), method='POST')
        self.assertEqual(resp.status_code, 403)

        resp = self.url_open(f'/api/v1/assessments/sessions/{session["id"]}/cancel', headers=headers, method='POST')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['state'], 'cancelled')

    def test_coordinator_sees_all_exams(self):
        self._create_exam()
        resp = self.url_open('/api/v1/assessments/exams', headers=self._headers('assess_api_coordinator', 'CoordPass1!'))
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()['meta']['total'], 1)

    # -- helpers for the detail / grading / authoring routes ------------------------

    def _published_exam(self):
        exam = self._create_exam()
        question = self.env['bxi.exam.question'].sudo().create({
            'exam_id': exam['id'], 'question_type': 'mcq', 'question_text': 'What is 3+3?', 'marks': 4})
        correct = self.env['bxi.exam.question.option'].sudo().create(
            {'question_id': question.id, 'option_text': '6', 'is_correct': True})
        self.env['bxi.exam.question.option'].sudo().create(
            {'question_id': question.id, 'option_text': '7', 'is_correct': False})
        self.url_open(f"/api/v1/assessments/exams/{exam['id']}/publish", headers=self._teacher_headers(), method='POST')
        return exam['id'], question, correct

    def _submitted(self, student=None):
        exam_id, question, correct = self._published_exam()
        headers = self._teacher_headers()
        session = self.url_open('/api/v1/assessments/sessions', headers=headers, json={
            'exam_id': exam_id, 'class_id': self.course.id, 'student_ids': [(student or self.student).id],
        }).json()['data']
        submission = self.env['bxi.assessment.submission'].sudo().search([('session_id', '=', session['id'])])
        self.url_open(f'/api/v1/assessments/submissions/{submission.id}/answers', headers=headers, json={
            'answers': [{'question_id': question.id, 'selected_option_id': correct.id}]})
        self.url_open(f'/api/v1/assessments/submissions/{submission.id}/mark-submitted', headers=headers, method='POST')
        return exam_id, session['id'], submission.id

    def _other_teacher(self):
        return self._headers('assess_api_other_teacher', 'OtherTeacherPass1!')

    def test_exam_detail_and_reset_to_draft(self):
        exam_id, _question, _correct = self._published_exam()
        detail = self.url_open(f'/api/v1/assessments/exams/{exam_id}', headers=self._teacher_headers())
        self.assertEqual(detail.status_code, 200, detail.text)
        data = detail.json()['data']
        self.assertEqual((data['state'], data['question_count'], data['total_marks']), ('published', 1, 4.0))
        self.assertEqual(self.url_open('/api/v1/assessments/exams/999999', headers=self._teacher_headers()).status_code, 404)

        url = f'/api/v1/assessments/exams/{exam_id}/reset-to-draft'
        self.assertEqual(self.url_open(url, headers=self._other_teacher(), method='POST').status_code, 403)
        reset = self.url_open(url, headers=self._teacher_headers(), method='POST')
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(reset.json()['data']['state'], 'draft')

    def test_session_and_submission_detail(self):
        student_user = mail_new_test_user(
            self.env, login='assess_api_student', groups='base.group_user', password='StudentPass1!')
        student = self._create_student('ASSAPI-002', user=student_user)
        exam_id, session_id, submission_id = self._submitted(student)

        session = self.url_open(f'/api/v1/assessments/sessions/{session_id}', headers=self._teacher_headers())
        self.assertEqual(session.status_code, 200, session.text)
        self.assertEqual((session.json()['data']['exam_id'], session.json()['data']['student_ids']), (exam_id, [student.id]))
        self.assertEqual(self.url_open('/api/v1/assessments/sessions/999999', headers=self._teacher_headers()).status_code, 404)

        url = f'/api/v1/assessments/submissions/{submission_id}'
        mine = self.url_open(url, headers=self._headers('assess_api_student', 'StudentPass1!'))
        self.assertEqual(mine.status_code, 200, mine.text)
        self.assertEqual(mine.json()['data']['status'], 'submitted')
        self.assertEqual(len(mine.json()['data']['answers']), 1)
        self.assertEqual(self.url_open(url, headers=self._teacher_headers()).status_code, 200)
        self.assertEqual(self.url_open(url, headers=self._other_teacher()).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/assessments/submissions/999999',
                                       headers=self._teacher_headers()).status_code, 404)

    def test_autograde_all(self):
        _exam_id, session_id, submission_id = self._submitted()
        url = f'/api/v1/assessments/sessions/{session_id}/autograde-all'
        self.assertEqual(self.url_open(url, headers=self._other_teacher(), method='POST').status_code, 403)
        # The bulk wizard insists on an AI key even when every question is MCQ.
        no_key = self.url_open(url, headers=self._teacher_headers(), method='POST')
        self.assertEqual(no_key.status_code, 400)
        self.assertIn('AI grading is not configured', no_key.json()['error']['message'])
        with patch.object(type(self.env['bxi.ai.client']), '_get_config', autospec=True,
                          return_value={'api_key': 'test-key'}):
            graded = self.url_open(url, headers=self._teacher_headers(), method='POST')
        self.assertEqual(graded.status_code, 200, graded.text)
        self.assertEqual((graded.json()['data']['graded_count'], graded.json()['data']['failed_count']), (1, 0))
        self.assertEqual(graded.json()['data']['submissions'][0]['id'], submission_id)
        self.assertEqual(graded.json()['data']['submissions'][0]['total_score'], 4.0)
        # Nothing left in "submitted" state.
        again = self.url_open(url, headers=self._teacher_headers(), method='POST')
        self.assertEqual(again.json()['error']['code'], 'nothing_to_grade')

    def test_re_evaluate(self):
        _exam_id, session_id, submission_id = self._submitted()
        self.url_open(f'/api/v1/assessments/submissions/{submission_id}/auto-grade',
                      headers=self._teacher_headers(), method='POST')
        url = f'/api/v1/assessments/submissions/{submission_id}/re-evaluate'
        self.assertEqual(self.url_open(url, headers=self._teacher_headers(), json={'marks_adjustment': 1})
                         .json()['error']['code'], 'missing_reason')
        self.assertEqual(self.url_open(url, headers=self._other_teacher(),
                                       json={'marks_adjustment': 1, 'reason': 'x'}).status_code, 403)
        resp = self.url_open(url, headers=self._teacher_headers(), json={'marks_adjustment': -1.5, 'reason': 'Working missing'})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['status'], 'reviewed')
        self.assertEqual(resp.json()['data']['manual_adjustment'], -1.5)
        self.assertEqual(resp.json()['data']['total_score'], 2.5)

    @staticmethod
    def _xlsx(rows):
        book = Workbook()
        sheet = book.active
        sheet.append(['Question Text', 'Type', 'Marks', 'Option A', 'Option B', 'Option C', 'Option D',
                      'Correct Option', 'Sample Answer/Keywords'])
        for row in rows:
            sheet.append(row)
        buf = io.BytesIO()
        book.save(buf)
        return base64.b64encode(buf.getvalue()).decode()

    def test_import_questions(self):
        exam = self._create_exam()
        url = f"/api/v1/assessments/exams/{exam['id']}/import-questions"
        data = self._xlsx([
            ['Capital of France?', 'MCQ', 2, 'Paris', 'Rome', None, None, 'A', None],
            ['Define photosynthesis.', 'Short Answer', 3, None, None, None, None, None, 'light, chlorophyll'],
        ])
        upload = {'attachments': [{'name': 'questions.xlsx', 'data': data}]}
        self.assertEqual(self.url_open(url, headers=self._other_teacher(), json=upload).status_code, 403)
        self.assertEqual(self.url_open(url, headers=self._teacher_headers(), json={}, method='POST')
                         .json()['error']['code'], 'missing_file')
        self.assertEqual(self.url_open(url, headers=self._teacher_headers(), json={
            'attachments': [{'name': 'questions.txt', 'data': data}]}).status_code, 400)

        resp = self.url_open(url, headers=self._teacher_headers(), json=upload)
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(resp.json()['data']['imported'], 2)
        questions = {q['question_text']: q for q in resp.json()['data']['questions']}
        self.assertEqual(questions['Capital of France?']['question_type'], 'mcq')
        self.assertEqual(questions['Define photosynthesis.']['marks'], 3.0)

        exam_id, _question, _correct = self._published_exam()
        published = self.url_open(f'/api/v1/assessments/exams/{exam_id}/import-questions',
                                  headers=self._teacher_headers(), json=upload)
        self.assertEqual(published.json()['error']['code'], 'exam_published')

    def test_ai_generate(self):
        rows = [
            {'question_type': 'mcq', 'question_text': 'AI Q1', 'marks': 1,
             'options': [{'option_text': 'yes', 'is_correct': True}, {'option_text': 'no', 'is_correct': False}]},
            {'question_type': 'short_answer', 'question_text': 'AI Q2', 'marks': 2, 'sample_answer_keywords': 'k'},
        ]
        payload = {'class_id': self.course.id, 'subject_id': self.subject.id, 'topic': 'Fractions', 'question_count': 2}
        client = type(self.env['bxi.ai.client'])
        with patch.object(client, 'generate_questions', autospec=True, return_value=rows) as generate:
            student_user = mail_new_test_user(self.env, login='assess_api_ai_student', groups='base.group_user',
                                              password='StudentPass1!')
            self._create_student('ASSAPI-003', user=student_user)
            self.assertEqual(self.url_open('/api/v1/assessments/exams/ai-generate', json=payload,
                                           headers=self._headers('assess_api_ai_student', 'StudentPass1!')).status_code, 403)
            self.assertEqual(self.url_open('/api/v1/assessments/exams/ai-generate', headers=self._teacher_headers(),
                                           json=dict(payload, topic='')).json()['error']['code'], 'missing_topic')
            self.assertFalse(generate.called)

            resp = self.url_open('/api/v1/assessments/exams/ai-generate', headers=self._teacher_headers(), json=payload)
            self.assertEqual(resp.status_code, 201, resp.text)
            data = resp.json()['data']
            self.assertEqual((data['source'], data['state'], data['teacher']), ('ai', 'draft', self.faculty.display_name))
            self.assertEqual([q['question_text'] for q in data['questions']], ['AI Q1', 'AI Q2'])
            self.assertEqual(generate.call_args.kwargs['topic'], 'Fractions')

            # Regenerating into a published exam is refused before the AI is called.
            calls = generate.call_count
            exam_id, _question, _correct = self._published_exam()
            refused = self.url_open('/api/v1/assessments/exams/ai-generate', headers=self._teacher_headers(),
                                    json=dict(payload, exam_id=exam_id))
            self.assertEqual(refused.json()['error']['code'], 'exam_published')
            self.assertEqual(generate.call_count, calls)

    def test_session_list_scoped_to_teacher(self):
        _exam_id, session_id, _submission_id = self._submitted()
        own = self.url_open('/api/v1/assessments/sessions', headers=self._teacher_headers())
        self.assertEqual(own.status_code, 200, own.text)
        self.assertEqual([s['id'] for s in own.json()['data']['sessions']], [session_id])
        self.assertEqual(self.url_open('/api/v1/assessments/sessions', headers=self._other_teacher())
                         .json()['data']['sessions'], [])
        coordinator = self.url_open('/api/v1/assessments/sessions', headers=self._headers('assess_api_coordinator', 'CoordPass1!'))
        self.assertIn(session_id, [s['id'] for s in coordinator.json()['data']['sessions']])
