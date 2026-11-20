# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The student app screens: Tasks, Smart Calendar, Notifications, Notes,
doubts, community, careers, study tips, the dashboard, the Info page, the
digital library and the admission application."""
import base64
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase

PDF = base64.b64encode(b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n').decode()


@tagged('post_install', '-at_install')
class TestStudentAppApi(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student_user = mail_new_test_user(cls.env, login='sa_student', password='StudentPass1!',
                                              groups='base.group_portal')
        cls.other_user = mail_new_test_user(cls.env, login='sa_other', password='OtherPass1!',
                                            groups='base.group_portal')
        cls.parent_user = mail_new_test_user(cls.env, login='sa_parent', password='ParentPass1!',
                                             groups='base.group_portal')
        cls.teacher_user = mail_new_test_user(cls.env, login='sa_teacher', password='TeacherPass1!',
                                              groups='base.group_user,openeducat_core.group_op_faculty')
        mail_new_test_user(cls.env, login='sa_coord', password='CoordPass1!',
                           groups='base.group_user,bxi_academic_management.group_academic_coordinator')
        cls.course, cls.sec_a = cls._create_class('SA9')
        cls.sec_b = cls.env['op.batch'].create({'name': 'SA9 B', 'code': 'SA9-B2', 'course_id': cls.course.id,
                                                'start_date': '2026-01-01', 'end_date': '2027-12-31'})
        cls.maths = cls.env['op.subject'].create({'name': 'SA Mathematics', 'code': 'SA-MATH'})
        cls.art = cls.env['op.subject'].create({'name': 'SA Art', 'code': 'SA-ART'})
        cls.course.subject_ids = [(6, 0, (cls.maths | cls.art).ids)]
        cls.student = cls._create_student('SA-001', first_name='Alex', last_name='Johnson', user=cls.student_user)
        cls._enroll(cls.student, cls.course, cls.sec_a)
        cls.other = cls._create_student('SA-002', first_name='Other', last_name='Kid', user=cls.other_user)
        cls._enroll(cls.other, cls.course, cls.sec_b)
        cls._create_parent(cls.parent_user, cls.student)
        cls.teacher = cls._create_faculty(cls.teacher_user, first_name='Sarah', last_name='Johnson')
        board = cls.env['bxi.board'].create({'name': 'SA Board'})
        curriculum = cls.env['bxi.curriculum'].create({'name': 'SA Curriculum', 'board_id': board.id,
                                                       'description': 'x', 'class_ids': [(6, 0, cls.course.ids)]})
        cls.env['bxi.subject.mapping'].create({'subject_id': cls.maths.id, 'class_id': cls.course.id,
                                               'teacher_id': cls.teacher.id, 'curriculum_id': curriculum.id})
        cls.env.company.resource_calendar_id.tz = 'Asia/Kolkata'

    def _post(self, url, body, login='sa_student', password='StudentPass1!'):
        return self.url_open(url, headers=self._headers(login, password), json=body, method='POST')

    def _get(self, url, login='sa_student', password='StudentPass1!'):
        return self.url_open(url, headers=self._headers(login, password))

    def _data(self, resp):
        self.assertLess(resp.status_code, 300, resp.text)
        return resp.json()['data']

    def _error(self, resp, status, code):
        self.assertEqual(resp.status_code, status, resp.text)
        self.assertEqual(resp.json()['error']['code'], code)

    def _homework(self, name, due, subject=None):
        assignment = self.env['op.assignment'].create({
            'name': name, 'course_id': self.course.id, 'batch_id': self.sec_a.id,
            'subject_id': (subject or self.maths).id, 'faculty_id': self.teacher.id,
            'assignment_type': self.env['grading.assignment.type'].search([], limit=1).id or
            self.env['grading.assignment.type'].create({'name': 'SA Homework', 'code': 'SAHW'}).id,
            'issued_date': fields.Datetime.now() - timedelta(days=3), 'submission_date': due,
            'description': 'Do it', 'allocation_ids': [(6, 0, self.student.ids)], 'point': 25,
            'bxi_chapter': 'Algebra', 'bxi_difficulty': 'medium', 'bxi_learning_objectives': 'Solve\nGraph',
            'bxi_requirements': 'Submit in PDF'})
        assignment.act_publish()
        return assignment

    # -- Tasks, calendar, notifications ------------------------------------------

    def test_tasks_screen(self):
        now = fields.Datetime.now()
        overdue = self._homework('SA Lab Report', now - timedelta(days=1))
        self._homework('SA Quadratics', now + timedelta(days=5))
        done = self._homework('SA Art Sketch', now + timedelta(days=6), subject=self.art)
        self.env['op.assignment.sub.line'].create({'assignment_id': done.id, 'student_id': self.student.id,
                                                   'description': 'done', 'state': 'submit'})
        data = self._data(self._get('/api/v1/assignments'))
        self.assertEqual({k: data['counts'][k] for k in ('total', 'completed', 'pending', 'overdue')},
                         {'total': 3, 'completed': 1, 'pending': 2, 'overdue': 1})
        statuses = {a['name']: a['task_status'] for a in data['assignments']}
        self.assertEqual(statuses['SA Lab Report'], 'overdue')
        self.assertEqual(statuses['SA Art Sketch'], 'completed')
        only_art = self._data(self._get('/api/v1/assignments?subject_id=%s' % self.art.id))['assignments']
        self.assertEqual([a['name'] for a in only_art], ['SA Art Sketch'])
        overdue_only = self._data(self._get('/api/v1/assignments?status=overdue'))['assignments']
        self.assertEqual([a['id'] for a in overdue_only], overdue.ids)
        self._error(self._get('/api/v1/assignments?status=late'), 400, 'invalid_status')

        detail = self._data(self._get('/api/v1/assignments/%s' % overdue.id))
        self.assertEqual((detail['chapter'], detail['difficulty'], detail['points']), ('Algebra', 'medium', 25.0))
        self.assertEqual(detail['learning_objectives'], ['Solve', 'Graph'])
        self.assertEqual([t['name'] for t in detail['related_tasks']], ['SA Quadratics'])

        calendar = self._data(self._get('/api/v1/calendar?date_from=%s&date_to=%s' % (
            (now - timedelta(days=2)).date(), (now + timedelta(days=10)).date())))['items']
        self.assertEqual(len([i for i in calendar if i['type'] == 'assignment']), 3)

    def test_notification_tabs_and_exam_alert(self):
        Notification = self.env['bxi.notification']
        Notification._notify(self.student_user, 'Fee due', 'Pay', category='fee_due', push=False)
        Notification._notify(self.student_user, 'Badge', 'Math Master', category='achievement', push=False)
        exam_type = self.env['op.exam.type'].create({'name': 'SA Term', 'code': 'SAT'})
        session = self.env['op.exam.session'].create({
            'name': 'SA Mid-Term', 'course_id': self.course.id, 'batch_id': self.sec_a.id, 'exam_code': 'SAMT',
            'start_date': fields.Date.today(), 'end_date': fields.Date.today() + timedelta(days=3),
            'exam_type': exam_type.id})
        session.act_schedule()
        self._homework('SA Due Soon', fields.Datetime.now() + timedelta(hours=20))
        counts = self._data(self._get('/api/v1/notifications/counts'))
        self.assertEqual((counts['tabs']['exams'], counts['tabs']['achievements']), (1, 1))
        self.assertEqual(counts['tabs']['assignments'], 1, 'The new homework alert.')
        self.assertEqual((counts['quick_actions']['urgent'], counts['quick_actions']['assignments_due_soon']), (1, 1))
        exams = self._data(self._get('/api/v1/notifications?tab=exams'))['notifications']
        self.assertEqual(exams[0]['title'], 'Exam scheduled: SA Mid-Term')
        self.assertEqual(exams[0]['tab'], 'exams')
        self._error(self._get('/api/v1/notifications?tab=nope'), 400, 'invalid_tab')

    # -- Notes ----------------------------------------------------------------------

    def test_notes(self):
        created = self._post('/api/v1/notes', {
            'title': 'Quadratic Equations', 'subject_id': self.maths.id, 'class_id': self.course.id,
            'section_ids': [self.sec_a.id], 'chapter': 'Chapter 8', 'priority': 'high', 'tags': ['Exam Topic'],
            'summary': 'Standard form', 'key_points': ['ax2 + bx + c = 0', 'Discriminant'],
            'content': '<p>%s</p>' % ('word ' * 450), 'attachments': [{'data': PDF, 'filename': 'sheet.pdf'}],
        }, 'sa_teacher', 'TeacherPass1!')
        self.assertEqual(created.status_code, 201, created.text)
        note = created.json()['data']
        self.assertEqual((note['state'], note['read_minutes'], note['tags']), ('published', 3, ['Exam Topic']))

        notes = self._data(self._get('/api/v1/notes'))
        self.assertEqual([n['id'] for n in notes['today']], [note['id']])
        self.assertEqual(notes['subjects'], [{'id': self.maths.id, 'name': 'SA Mathematics', 'count': 1}])
        self.assertEqual(self._data(self._get('/api/v1/notes', 'sa_other', 'OtherPass1!'))['today'], [],
                         'Section B does not see a note for section A.')
        self._error(self._get('/api/v1/notes/%s' % note['id'], 'sa_other', 'OtherPass1!'), 404, 'not_found')

        detail = self._data(self._get('/api/v1/notes/%s' % note['id']))
        self.assertEqual(detail['key_points'], ['ax2 + bx + c = 0', 'Discriminant'])
        attachment = detail['attachments'][0]['id']
        self.assertEqual(self._get('/api/v1/notes/%s/attachments/%s' % (note['id'], attachment)).status_code, 200)
        pdf = self._get('/api/v1/notes/%s/pdf' % note['id'])
        self.assertEqual(pdf.status_code, 200, pdf.text)
        # Odoo renders reports as HTML while tests run; the name says PDF.
        self.assertIn('Note%20-%20Quadratic%20Equations.pdf', pdf.headers['Content-Disposition'])
        self.assertIn(b'Quadratic Equations', pdf.content)
        self.assertTrue(self._data(self._post('/api/v1/notes/%s/bookmark' % note['id'], {}))['bookmarked'])
        self.assertEqual(len(self._data(self._get('/api/v1/notes?bookmarked=1'))['today']), 1)

        comment = self._data(self._post('/api/v1/notes/%s/comments' % note['id'], {'body': 'Very helpful!'}))
        self._post('/api/v1/notes/%s/comments' % note['id'], {'body': 'Thanks', 'parent_id': comment['id']},
                   'sa_teacher', 'TeacherPass1!')
        liked = self._data(self._post('/api/v1/notes/comments/%s/like' % comment['id'], {}))
        self.assertEqual((liked['likes'], liked['liked'], len(liked['replies'])), (1, True, 1))
        self._error(self._post('/api/v1/notes/%s/comments' % note['id'], {'body': ' '}), 400, 'missing_body')

        self._error(self._post('/api/v1/notes/%s/update' % note['id'], {'title': 'X'}), 403, 'forbidden')
        updated = self._data(self._post('/api/v1/notes/%s/update' % note['id'], {'publish': False, 'priority': 'normal'},
                             'sa_teacher', 'TeacherPass1!'))
        self.assertEqual((updated['state'], updated['priority']), ('draft', 'normal'))
        self._error(self._get('/api/v1/notes/%s' % note['id'], 'sa_other', 'OtherPass1!'), 404, 'not_found')

    # -- Doubts and community ----------------------------------------------------

    def test_doubts(self):
        asked = self._post('/api/v1/doubts', {'question': 'How to solve quadratic equations?',
                                              'subject_id': self.maths.id})
        self.assertEqual(asked.status_code, 201, asked.text)
        doubt = asked.json()['data']
        self.assertEqual(doubt['teacher']['id'], self.teacher.id, 'Routed by Subject Mapping.')
        self.assertTrue(self.env['bxi.notification'].search_count([('user_id', '=', self.teacher_user.id),
                                                                    ('category', '=', 'doubt')]))
        self._error(self._post('/api/v1/doubts', {'question': 'x'}, 'sa_parent', 'ParentPass1!'), 403, 'forbidden')
        self._error(self._post('/api/v1/doubts/%s/answer' % doubt['id'], {'answer': 'Use the formula'}), 403,
                    'forbidden')
        teacher_list = self._data(self._get('/api/v1/doubts', 'sa_teacher', 'TeacherPass1!'))
        self.assertEqual([d['id'] for d in teacher_list['doubts']], [doubt['id']])
        answered = self._data(self._post('/api/v1/doubts/%s/answer' % doubt['id'], {'answer': 'Use the quadratic formula'},
                              'sa_teacher', 'TeacherPass1!'))
        self.assertEqual(answered['state'], 'answered')
        mine = self._data(self._get('/api/v1/doubts'))
        self.assertEqual((mine['counts']['answered'], mine['counts']['solved_today']), (1, 1))
        self._error(self._get('/api/v1/doubts/%s' % doubt['id'], 'sa_other', 'OtherPass1!'), 404, 'not_found')

    def test_community(self):
        post = self._data(self._post('/api/v1/community/posts', {'kind': 'discussion', 'title': 'Math Study Group',
                                                      'body': 'Who is in?'}))
        self.assertEqual(post['section']['id'], self.sec_a.id)
        self.assertEqual(self._data(self._get('/api/v1/community/posts', 'sa_other', 'OtherPass1!'))['posts'],
                         [], 'Another section does not see it.')
        self._error(self._get('/api/v1/community/posts/%s' % post['id'], 'sa_other', 'OtherPass1!'), 404,
                    'not_found')
        replied = self._data(self._post('/api/v1/community/posts/%s/replies' % post['id'], {'body': 'Me!'},
                             'sa_teacher', 'TeacherPass1!'))
        self.assertEqual(replied['reply_count'], 1)
        self.assertEqual(self._data(self._post('/api/v1/community/posts/%s/like' % post['id'], {}))['likes'], 1)
        self._error(self._post('/api/v1/community/posts', {'title': 'x'}, 'sa_parent', 'ParentPass1!'), 403,
                    'forbidden')
        self._error(self._post('/api/v1/community/posts/%s/hide' % post['id'], {}), 403, 'forbidden')

        # Three classmates' reports hide it for review.
        reporters = [mail_new_test_user(self.env, login='sa_rep%s' % i, password='RepPass1!',
                                        groups='base.group_portal') for i in range(3)]
        for index, user in enumerate(reporters):
            student = self._create_student('SA-R%s' % index, user=user)
            self._enroll(student, self.course, self.sec_a)
            self._post('/api/v1/community/posts/%s/report' % post['id'], {'reason': 'spam'}, user.login, 'RepPass1!')
        self.assertEqual(self.env['bxi.community.post'].browse(post['id']).state, 'hidden')
        self._error(self._get('/api/v1/community/posts/%s' % post['id']), 404, 'not_found')
        shown = self._data(self._post('/api/v1/community/posts/%s/unhide' % post['id'], {}, 'sa_teacher',
                           'TeacherPass1!'))
        self.assertEqual(shown['state'], 'visible')

    # -- Careers, study tips, dashboard, info --------------------------------------

    def _exam_result(self, subject, marks, code):
        exam_type = self.env['op.exam.type'].search([], limit=1) or self.env['op.exam.type'].create(
            {'name': 'SA Unit', 'code': 'SAU'})
        session = self.env['op.exam.session'].create({
            'name': 'SA Unit %s' % code, 'course_id': self.course.id, 'batch_id': self.sec_a.id,
            'exam_code': 'SAS%s' % code, 'start_date': fields.Date.today(), 'end_date': fields.Date.today(),
            'exam_type': exam_type.id})
        exam = self.env['op.exam'].create({
            'session_id': session.id, 'subject_id': subject.id, 'exam_code': 'SAE%s' % code, 'name': 'SA %s' % code,
            'start_time': fields.Datetime.now() - timedelta(hours=2), 'end_time': fields.Datetime.now() - timedelta(hours=1),
            'total_marks': 100, 'min_marks': 35})
        self.env['op.result.line'].create({'exam_id': exam.id, 'student_id': self.student.id, 'marks': marks})

    def test_careers_tips_dashboard_and_info(self):
        self._exam_result(self.maths, 92, 'M')
        self._exam_result(self.art, 60, 'A')
        careers = self._data(self._get('/api/v1/student/careers'))
        names = [c['name'] for c in careers['careers']]
        self.assertEqual(names[0], 'Technical / Engineering', 'Mathematics is the strongest subject.')
        self.assertIn({'subject': 'SA Art', 'percentage': 60.0}, careers['scores'])

        tips = self._data(self._get('/api/v1/student/study-tips'))['tips']
        self.assertIn({'type': 'weak_area', 'subject': 'SA Art', 'percentage': 60.0,
                       'text': 'Focus on SA Art - your weak area'}, tips)

        self._homework('SA Dashboard HW', fields.Datetime.now() + timedelta(days=2))
        dashboard = self._data(self._get('/api/v1/student/dashboard'))
        self.assertEqual(dashboard['student']['section']['id'], self.sec_a.id)
        self.assertEqual(dashboard['homework']['pending'], 1)
        self.assertEqual(dashboard['careers'][0]['name'], 'Technical / Engineering')
        self.assertEqual([t['percentage'] for t in dashboard['recent_tests']][:2], [60.0, 92.0])
        parent_view = self._get('/api/v1/student/dashboard', 'sa_parent', 'ParentPass1!')
        self.assertEqual(parent_view.json()['data']['student']['id'], self.student.id, 'One child: implied.')
        self._error(self._get('/api/v1/student/dashboard?student_id=%s' % self.student.id, 'sa_other', 'OtherPass1!'),
                    403, 'forbidden')

        self.env.company.write({
            'bxi_about_tagline': 'Smart learning', 'bxi_about_mission': '<p>Every student</p>',
            'bxi_value_ids': [(0, 0, {'name': 'Student-Centric', 'icon': 'heart'})],
            'bxi_team_member_ids': [(0, 0, {'name': 'Dr. Sarah Johnson', 'role': 'CEO & Founder'})]})
        info = self._data(self._get('/api/v1/school/info'))
        self.assertEqual((info['tagline'], info['values'][0]['name'], info['team'][0]['role']),
                         ('Smart learning', 'Student-Centric', 'CEO & Founder'))
        self.assertGreaterEqual(info['stats']['students'], 2)

    # -- Digital library ------------------------------------------------------------

    def test_digital_library(self):
        genre = self.env['op.media.genre'].create({'name': 'SA Algebra Genre'})
        author = self.env['op.author'].create({'name': 'SA Author'})
        publisher = self.env['op.publisher'].create({'name': 'SA Publisher'})
        attachment = self.env['ir.attachment'].create({'name': 'algebra.pdf', 'datas': PDF,
                                                       'mimetype': 'application/pdf'})
        book = self.env['op.media'].create({
            'name': 'SA Advanced Algebra', 'genre_id': genre.id, 'author_ids': [(6, 0, author.ids)],
            'publisher_ids': [(6, 0, publisher.ids)], 'subject_ids': [(6, 0, self.maths.ids)],
            'attachment_ids': [(6, 0, attachment.ids)]})
        other_book = self.env['op.media'].create({
            'name': 'SA Algebra Workbook', 'genre_id': genre.id, 'author_ids': [(6, 0, author.ids)],
            'publisher_ids': [(6, 0, publisher.ids)], 'subject_ids': [(6, 0, self.maths.ids)]})

        saved = self._post('/api/v1/library/catalog/%s/progress' % book.id,
                           {'current_page': 13, 'total_pages': 20, 'chapter': 'Chapter 5'})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()['data']['progress']['percent'], 65.0)
        self._error(self._post('/api/v1/library/catalog/%s/progress' % book.id, {'percent': 120}), 400,
                    'invalid_progress')
        self.assertTrue(self._data(self._post('/api/v1/library/reading-list/%s' % other_book.id, {}))[
            'in_reading_list'])

        data = self._data(self._get('/api/v1/library/digital'))
        self.assertEqual((data['stats']['reading_now'], data['stats']['day_streak']), (1, 1))
        self.assertEqual(data['continue_reading'][0]['progress']['chapter'], 'Chapter 5')
        self.assertIn({'id': genre.id, 'name': 'SA Algebra Genre', 'count': 2}, data['categories'])
        self.assertIn(book.id, [b['id'] for b in data['trending']])
        recommended = {b['id']: b for b in data['recommendations']}
        self.assertIn(other_book.id, recommended, 'A class-subject book not started yet.')
        self.assertTrue(recommended[other_book.id]['in_reading_list'])
        self.assertEqual([b['id'] for b in self._data(self._get('/api/v1/library/reading-list'))['books']],
                         other_book.ids)
        file = self._get('/api/v1/library/catalog/%s/file' % book.id)
        self.assertEqual(file.status_code, 200)
        self._error(self._get('/api/v1/library/catalog/%s/file' % other_book.id), 404, 'no_file')

    # -- Admission application ----------------------------------------------------

    def test_admission_application(self):
        register = self.env['op.admission.register'].create({
            'name': 'SA Intake', 'course_id': self.course.id, 'start_date': fields.Date.today() - timedelta(days=1),
            'end_date': fields.Date.today() + timedelta(days=30), 'max_count': 50, 'min_count': 1,
            'state': 'application'})
        self._error(self._post('/api/v1/admissions/applications', {'register_id': register.id,
                                                                   'first_name': 'Alex'}), 400, 'missing_last_name')
        started = self._post('/api/v1/admissions/applications', {
            'register_id': register.id, 'first_name': 'Alex', 'last_name': 'Johnson', 'birth_date': '2012-04-05',
            'email': 'alex@sa.test', 'mobile': '9800000001', 'gender': 'm'})
        self.assertEqual(started.status_code, 201, started.text)
        app = started.json()['data']
        self.assertEqual((app['state'], app['step'], app['can_submit']), ('draft', 'academic', False))
        url = '/api/v1/admissions/applications/%s' % app['id']

        self._error(self._post(url + '/submit', {}), 400, 'incomplete')
        updated = self._data(self._post(url + '/update', {
            'prev_institute_id': 'SA Primary', 'prev_course_id': 'Class 8', 'prev_result': 'A',
            'documents': {'transcripts': [PDF], 'test_scores': [{'data': PDF, 'filename': 'SAT.pdf'}],
                          'recommendations': [PDF], 'id_proof': [PDF]},
            'statement': 'I love maths.', 'step': 'documents'}))
        self.assertEqual(updated['documents']['test_scores']['files'][0]['name'], 'SAT.pdf')
        self.assertEqual([m['field'] for m in updated['missing']], ['recommendations'],
                         'Two letters of recommendation are needed.')
        kept = updated['documents']['recommendations']['files'][0]['id']
        ready = self._data(self._post(url + '/update', {'documents': {'recommendations': [kept, PDF]}}))
        self.assertTrue(ready['can_submit'])
        self._error(self._post(url + '/update', {'documents': {'recommendations': [kept, PDF, PDF]}}), 400,
                    'too_many_files')
        submitted = self._data(self._post(url + '/submit', {}))
        self.assertEqual(submitted['state'], 'submit')
        self._error(self._post(url + '/update', {'statement': 'changed'}), 400, 'already_submitted')
        self._error(self._get(url, 'sa_other', 'OtherPass1!'), 404, 'not_found')
        mine = self._data(self._get('/api/v1/admissions/applications'))['applications']
        self.assertEqual([a['id'] for a in mine], [app['id']])

        draft = self._data(self._post('/api/v1/admissions/applications', {
            'register_id': register.id, 'first_name': 'Sam', 'last_name': 'J', 'birth_date': '2012-01-01',
            'email': 'sam@sa.test', 'gender': 'm'}))
        self.assertTrue(self._data(self._post('/api/v1/admissions/applications/%s/discard' % draft['id'], {}))[
            'discarded'])
