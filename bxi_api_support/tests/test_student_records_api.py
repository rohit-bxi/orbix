# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Student-wise timetable, books and exams/tests:
/api/v1/student/timetable, /api/v1/student/books, /api/v1/student/exams."""
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestStudentRecordsApi(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student_user = mail_new_test_user(cls.env, login='sr_student', password='StudentPass1!',
                                              groups='base.group_portal')
        cls.other_user = mail_new_test_user(cls.env, login='sr_other', password='OtherPass1!',
                                            groups='base.group_portal')
        cls.parent_user = mail_new_test_user(cls.env, login='sr_parent', password='ParentPass1!',
                                             groups='base.group_portal')
        cls.teacher_user = mail_new_test_user(cls.env, login='sr_teacher', password='TeacherPass1!',
                                              groups='base.group_user,openeducat_core.group_op_faculty')
        cls.course, cls.sec_a = cls._create_class('SR9')
        cls.other_course, cls.other_sec = cls._create_class('SR8')
        cls.maths = cls.env['op.subject'].create({'name': 'SR Mathematics', 'code': 'SR-MATH'})
        cls.science = cls.env['op.subject'].create({'name': 'SR Science', 'code': 'SR-SCI'})
        cls.student = cls._create_student('SR-001', first_name='Riya', last_name='Shah', user=cls.student_user)
        cls.enrollment = cls._enroll(cls.student, cls.course, cls.sec_a)
        cls.enrollment.roll_number = '12'
        cls.other = cls._create_student('SR-002', first_name='Other', last_name='Kid', user=cls.other_user)
        cls._enroll(cls.other, cls.other_course, cls.other_sec)
        cls._create_parent(cls.parent_user, cls.student)
        cls.teacher = cls._create_faculty(cls.teacher_user, first_name='Meera', last_name='Iyer')

    def _get(self, url, login='sr_student', password='StudentPass1!'):
        return self.url_open(url, headers=self._headers(login, password))

    def _data(self, resp):
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()['data']

    def _error(self, resp, status, code):
        self.assertEqual(resp.status_code, status, resp.text)
        self.assertEqual(resp.json()['error']['code'], code)

    # -- access -------------------------------------------------------------------

    def test_access_rules(self):
        for url in ('/api/v1/student/timetable', '/api/v1/student/books', '/api/v1/student/exams'):
            self.assertEqual(self.url_open(url).status_code, 401)
            # The student and their parent get the student without sending an id.
            self.assertEqual(self._data(self._get(url))['student']['id'], self.student.id)
            self.assertEqual(self._data(self._get(url, 'sr_parent', 'ParentPass1!'))['student']['id'],
                             self.student.id)
            # Nobody else's child.
            self._error(self._get('%s?student_id=%s' % (url, self.other.id)), 403, 'forbidden')
            self._error(self._get('%s?student_id=%s' % (url, self.other.id), 'sr_parent', 'ParentPass1!'),
                        403, 'forbidden')
            self._error(self._get('%s?student_id=999999' % url), 404, 'not_found')
            # A teacher must name the student.
            self._error(self._get(url, 'sr_teacher', 'TeacherPass1!'), 400, 'missing_student_id')

    # -- timetable ----------------------------------------------------------------

    def test_weekly_timetable(self):
        Timing = self.env['op.timing']
        first = Timing.create({'name': 'SR P1', 'hour': '9', 'minute': '00', 'am_pm': 'am',
                               'start_time': 9.0, 'end_time': 9.75})
        second = Timing.create({'name': 'SR P2', 'hour': '9', 'minute': '45', 'am_pm': 'am',
                                'start_time': 9.75, 'end_time': 10.5})
        timetable = self.env['bxi.timetable'].create({'course_id': self.course.id, 'batch_id': self.sec_a.id})
        Line = self.env['bxi.timetable.line']
        Line.create({'timetable_id': timetable.id, 'day': 'monday', 'timing_id': second.id,
                     'subject_id': self.science.id, 'teacher_id': self.teacher.id})
        Line.create({'timetable_id': timetable.id, 'day': 'monday', 'timing_id': first.id,
                     'subject_id': self.maths.id, 'teacher_id': self.teacher.id})
        Line.create({'timetable_id': timetable.id, 'day': 'wednesday', 'timing_id': first.id,
                     'subject_id': self.maths.id})

        data = self._data(self._get('/api/v1/student/timetable'))
        self.assertEqual(data['student']['class']['id'], self.course.id)
        self.assertEqual(data['student']['section']['id'], self.sec_a.id)
        self.assertEqual(data['student']['roll_number'], '12')
        self.assertEqual(data['timetable_id'], timetable.id)
        self.assertEqual(data['total_periods'], 3)
        self.assertEqual([d['day'] for d in data['days']],
                         ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'])
        monday = data['days'][0]
        self.assertEqual([p['subject']['name'] for p in monday['periods']], ['SR Mathematics', 'SR Science'])
        self.assertEqual((monday['periods'][0]['start_time'], monday['periods'][0]['end_time']), ('09:00', '09:45'))
        self.assertEqual(monday['periods'][0]['teacher']['id'], self.teacher.id)
        self.assertEqual([s['start_time'] for s in data['time_slots']], ['09:00', '09:45'])
        self.assertIsNone(data['message'])

        # The section's teacher may look it up for the student; one day only.
        wednesday = self._data(self._get('/api/v1/student/timetable?student_id=%s&day=wednesday' % self.student.id,
                                         'sr_teacher', 'TeacherPass1!'))['days']
        self.assertEqual([d['day'] for d in wednesday], ['wednesday'])
        self.assertIsNone(wednesday[0]['periods'][0]['teacher'])
        self._error(self._get('/api/v1/student/timetable?day=sunday'), 400, 'invalid_day')

    def test_timetable_not_set_up(self):
        data = self._data(self._get('/api/v1/student/timetable'))
        self.assertIsNone(data['timetable_id'])
        self.assertEqual(data['total_periods'], 0)
        self.assertTrue(data['message'])

    # -- books --------------------------------------------------------------------

    def test_books(self):
        board = self.env['bxi.board'].create({'name': 'SR Board'})
        approved = self.env['bxi.curriculum'].create({
            'name': 'SR CBSE', 'board_id': board.id, 'description': 'x', 'approval_status': 'approved',
            'class_ids': [(6, 0, (self.course | self.other_course).ids)]})
        draft = self.env['bxi.curriculum'].create({
            'name': 'SR Draft', 'board_id': board.id, 'description': 'x',
            'class_ids': [(6, 0, self.course.ids)]})
        Media = self.env['op.media']
        maths_book = Media.create({'name': 'SR Maths Book', 'curriculum_id': approved.id,
                                   'course_ids': [(6, 0, self.course.ids)], 'subject_ids': [(6, 0, self.maths.ids)]})
        science_book = Media.create({'name': 'SR Science Book', 'curriculum_id': approved.id,
                                     'course_ids': [(6, 0, self.course.ids)],
                                     'subject_ids': [(6, 0, self.science.ids)]})
        Media.create({'name': 'SR Draft Book', 'curriculum_id': draft.id, 'course_ids': [(6, 0, self.course.ids)]})
        Media.create({'name': 'SR Other Class Book', 'curriculum_id': approved.id,
                      'course_ids': [(6, 0, self.other_course.ids)]})
        self.env['bxi.reading.progress'].create({'student_id': self.student.id, 'media_id': maths_book.id,
                                                 'percent': 40, 'current_page': 20, 'total_pages': 50})

        data = self._data(self._get('/api/v1/student/books'))
        self.assertEqual([b['title'] for b in data['smart_books']], ['SR Maths Book', 'SR Science Book'])
        progress = {b['id']: b['progress'] for b in data['smart_books']}
        self.assertEqual(progress[maths_book.id]['percent'], 40.0)
        self.assertIsNone(progress[science_book.id])
        self.assertEqual(data['summary']['smart_books'], 2)
        self.assertEqual(data['summary']['in_progress'], 1)
        self.assertEqual(data['library'], [])

        only_science = self._data(self._get('/api/v1/student/books?subject_id=%s' % self.science.id))
        self.assertEqual([b['id'] for b in only_science['smart_books']], science_book.ids)
        self._error(self._get('/api/v1/student/books?subject_id=abc'), 400, 'invalid_subject_id')

    # -- exams and tests --------------------------------------------------------------

    def _paper(self, session, name, start, state):
        paper = self.env['op.exam'].create({
            'session_id': session.id, 'subject_id': self.maths.id, 'exam_code': 'SR-%s' % name,
            'start_time': start, 'end_time': start + timedelta(hours=1), 'name': name,
            'total_marks': 50, 'min_marks': 20,
        })
        attendee = self.env['op.exam.attendees'].create({'exam_id': paper.id, 'student_id': self.student.id,
                                                         'marks': 40})
        paper.state = state
        return paper, attendee

    def test_exams_and_tests(self):
        exam_type = self.env['op.exam.type'].create({'name': 'SR Term', 'code': 'SRT'})
        today = fields.Date.today()
        session = self.env['op.exam.session'].create({
            'name': 'SR Term 1', 'course_id': self.course.id, 'batch_id': self.sec_a.id, 'exam_code': 'SRT1',
            'start_date': today - timedelta(days=5), 'end_date': today + timedelta(days=5),
            'exam_type': exam_type.id, 'state': 'schedule'})
        now = fields.Datetime.now()
        done, _attendee = self._paper(session, 'SR Done', now - timedelta(days=3), 'done')
        held, _attendee = self._paper(session, 'SR Held', now - timedelta(days=2), 'held')
        upcoming, _attendee = self._paper(session, 'SR Next', now + timedelta(days=2), 'schedule')
        self._paper(session, 'SR Cancelled', now + timedelta(days=3), 'cancel')

        quiz = self.env['bxi.exam'].create({'name': 'SR Algebra Quiz', 'class_id': self.course.id,
                                            'subject_id': self.maths.id, 'teacher_id': self.teacher.id})
        graded = self.env['bxi.assessment.session'].create({
            'exam_id': quiz.id, 'class_id': self.course.id, 'teacher_id': self.teacher.id,
            'exam_date': today - timedelta(days=1), 'student_ids': [(6, 0, self.student.ids)]})
        graded_sub = graded.submission_ids
        graded_sub.write({'status': 'reviewed', 'manual_adjustment': 0})
        pending = self.env['bxi.assessment.session'].create({
            'exam_id': quiz.id, 'class_id': self.course.id, 'teacher_id': self.teacher.id,
            'exam_date': today + timedelta(days=2), 'exam_time': 10.5, 'student_ids': [(6, 0, self.student.ids)]})
        self.env['bxi.assessment.session'].create({
            'exam_id': quiz.id, 'class_id': self.course.id, 'teacher_id': self.teacher.id,
            'exam_date': today + timedelta(days=3), 'student_ids': [(6, 0, self.student.ids)]}).action_cancel()

        data = self._data(self._get('/api/v1/student/exams', 'sr_parent', 'ParentPass1!'))
        papers = {e['id']: e for e in data['exams']}
        self.assertEqual(list(papers), [done.id, held.id, upcoming.id], 'Cancelled papers are left out.')
        self.assertEqual(papers[done.id]['result']['marks'], 40)
        self.assertEqual(papers[done.id]['result']['percentage'], 80.0)
        self.assertTrue(papers[done.id]['result']['passed'])
        self.assertIsNone(papers[held.id]['result'], 'Marks stay hidden until the paper is Done.')
        self.assertEqual(papers[held.id]['status'], 'completed')
        self.assertEqual(papers[upcoming.id]['status'], 'upcoming')

        tests = {t['session_id']: t for t in data['tests']}
        self.assertEqual(set(tests), {graded.id, pending.id}, 'Cancelled tests are left out.')
        self.assertEqual(tests[graded.id]['status'], 'completed')
        self.assertEqual(tests[graded.id]['submission_status'], 'reviewed')
        self.assertIsNotNone(tests[graded.id]['score'])
        self.assertEqual(tests[pending.id]['status'], 'upcoming')
        self.assertEqual(tests[pending.id]['time'], '10:30')
        self.assertIsNone(tests[pending.id]['score'])

        self.assertEqual(data['summary']['upcoming_exams'], 1)
        self.assertEqual(data['summary']['completed_exams'], 2)
        self.assertEqual(data['summary']['upcoming_tests'], 1)
        self.assertEqual(data['summary']['completed_tests'], 1)

        upcoming_only = self._data(self._get('/api/v1/student/exams?status=upcoming'))
        self.assertEqual([e['id'] for e in upcoming_only['exams']], upcoming.ids)
        self.assertEqual([t['session_id'] for t in upcoming_only['tests']], pending.ids)
        self._error(self._get('/api/v1/student/exams?status=late'), 400, 'invalid_status')

        # Another class's student sees none of it.
        other = self._data(self._get('/api/v1/student/exams', 'sr_other', 'OtherPass1!'))
        self.assertEqual((other['exams'], other['tests']), ([], []))

    def test_books_elearning_courses_joined_by_login(self):
        """The student joins courses as their login's contact, not the
        op.student contact."""
        if 'slide.channel' not in self.env:
            self.skipTest('eLearning not installed')
        channel = self.env['slide.channel'].create({'name': 'SR Algebra', 'enroll': 'public',
                                                    'visibility': 'connected', 'is_published': True})
        Slide = self.env['slide.slide']
        first = Slide.create({'name': 'SR Ch1', 'channel_id': channel.id, 'slide_category': 'article',
                              'html_content': '<p>x</p>', 'is_published': True, 'sequence': 1, 'completion_time': 0.5})
        Slide.create({'name': 'SR Ch2', 'channel_id': channel.id, 'slide_category': 'article',
                      'html_content': '<p>y</p>', 'is_published': True, 'sequence': 2, 'completion_time': 1.0})
        channel._action_add_members(self.student_user.partner_id)
        self.assertNotEqual(self.student_user.partner_id, self.student.partner_id)
        first.with_user(self.student_user)._action_mark_completed()
        books = self._data(self._get('/api/v1/student/books', 'sr_parent', 'ParentPass1!'))['elearning_books']
        self.assertEqual(len(books), 1)
        self.assertEqual((books[0]['id'], books[0]['chapter_index'], books[0]['chapter_count'], books[0]['hours_left']),
                         (channel.id, 2, 2, 1.0))
