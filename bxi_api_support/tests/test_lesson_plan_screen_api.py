# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The Create / Edit Lesson Plan screens on /api/v1/lesson-plans: every
starred field, the "+ Add" lists, typed names, the quarter taken from the
dates, and editing an approved plan."""
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase

URL = '/api/v1/lesson-plans'


@tagged('post_install', '-at_install')
class TestLessonPlanScreenApi(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        teacher_user = mail_new_test_user(cls.env, login='lps_teacher', password='TeacherPass1!',
                                          groups='base.group_user,openeducat_core.group_op_faculty')
        mail_new_test_user(cls.env, login='lps_other', password='OtherPass1!',
                           groups='base.group_user,openeducat_core.group_op_faculty')
        mail_new_test_user(cls.env, login='lps_coord', password='CoordPass1!',
                           groups='base.group_user,bxi_academic_management.group_academic_coordinator')
        cls.maths = cls.env['op.subject'].create({'name': 'LPS Mathematics', 'code': 'LPS-MATH'})
        cls.art = cls.env['op.subject'].create({'name': 'LPS Art', 'code': 'LPS-ART'})
        cls.class9 = cls.env['op.course'].create({'name': 'LPS Class 9', 'code': 'LPS-9',
                                                  'subject_ids': [(6, 0, cls.maths.ids)]})
        year = cls.env['op.academic.year'].create({'name': 'LPS AY', 'start_date': '2031-03-17',
                                                   'end_date': '2032-03-16'})
        Term = cls.env['op.academic.term']
        cls.half = Term.create({'name': 'LPS Half 1', 'term_start_date': '2031-03-17',
                                'term_end_date': '2031-09-30', 'academic_year_id': year.id})
        cls.q1 = Term.create({'name': 'LPS Q1', 'term_start_date': '2031-04-03', 'term_end_date': '2031-06-30',
                              'academic_year_id': year.id, 'parent_term': cls.half.id})
        cls.sarah = cls.env['op.faculty'].create({
            'first_name': 'Lpssarah', 'last_name': 'Johnson', 'gender': 'female', 'birth_date': '1985-01-01',
            'user_id': teacher_user.id})

    def _post(self, url, body, login='lps_teacher', password='TeacherPass1!'):
        return self.url_open(url, headers=self._headers(login, password), json=body, method='POST')

    def _error(self, resp, status, code):
        self.assertEqual(resp.status_code, status, resp.text)
        self.assertEqual(resp.json()['error']['code'], code)

    def _body(self, **overrides):
        body = {
            'subject': 'LPS Mathematics', 'class': 'LPS Class 9', 'duration': '5 days',
            'topic': 'Algebra - Linear Equations', 'learning_objectives': 'Solve linear equations',
            'activities': 'Board work, pair practice', 'resources': 'Textbook ch. 4',
            'assessment_method': 'Exit quiz', 'start_date': '02/05/2031', 'end_date': '06/05/2031',
            'plan_date': 'Monday, May 5, 2031',
            'recall_questions': ['What is a linear equation?'], 'class_work': ['Solving linear equations'],
            'teaching_aids': ['Whiteboard', 'markers'], 'home_work': ['Practice problems'],
            'remarks': ['Students showed good understanding'],
        }
        body.update(overrides)
        return {key: value for key, value in body.items() if value is not None}

    def test_create_from_the_full_screen(self):
        resp = self._post(URL, self._body())
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertEqual((data['teacher_id'], data['subject_id'], data['class_id']),
                         (self.sarah.id, self.maths.id, self.class9.id))
        self.assertEqual(data['quarter_id'], self.q1.id, 'The narrowest term covering the start date.')
        self.assertEqual((data['duration'], data['duration_days']), ('5 days', 5))
        self.assertEqual((data['start_date'], data['end_date'], data['plan_date'], data['plan_day']),
                         ('2031-05-02', '2031-05-06', '2031-05-05', 'Monday'))
        for key in ('topic', 'learning_objectives', 'activities', 'resources', 'assessment_method'):
            self.assertTrue(data[key], key)
        self.assertEqual([i['text'] for i in data['teaching_aids']], ['Whiteboard', 'markers'])
        self.assertEqual([i['text'] for i in data['remarks']], ['Students showed good understanding'])
        self.assertEqual(len(data['lines']), 6)
        self.assertEqual(data['state'], 'pending')

        # Remarks are optional; DD/MM/YYYY works for the Day and Date too.
        resp = self._post(URL, self._body(remarks=None, plan_date='03/05/2031', topic='Graphs'))
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(resp.json()['data']['remarks'], [])

    def test_starred_fields_and_checks(self):
        for key in ('subject', 'class', 'duration', 'topic', 'learning_objectives', 'activities', 'resources',
                    'assessment_method', 'start_date', 'end_date', 'plan_date', 'recall_questions',
                    'class_work', 'teaching_aids', 'home_work'):
            code = 'missing_%s' % ('%s_id' % key if key in ('subject', 'class') else key)
            self._error(self._post(URL, self._body(**{key: None})), 400, code)
        self._error(self._post(URL, self._body(class_work=['  '])), 400, 'missing_class_work')
        self._error(self._post(URL, self._body(activities='   ')), 400, 'missing_activities')
        self._error(self._post(URL, self._body(subject='Astrology')), 400, 'unknown_subject')
        self._error(self._post(URL, self._body(subject='LPS Art')), 400, 'subject_not_in_class')
        self._error(self._post(URL, self._body(end_date='01/05/2031')), 400, 'invalid_dates')
        self._error(self._post(URL, self._body(plan_date='10/05/2031')), 400, 'plan_date_outside_dates')
        self._error(self._post(URL, self._body(plan_date='Someday, 4 May')), 400, 'invalid_plan_date')
        self._error(self._post(URL, self._body(start_date='02/05/2040', end_date='03/05/2040',
                                               plan_date='02/05/2040')), 400, 'no_quarter')
        self.assertFalse(self.env['bxi.lesson.plan'].search([('class_id', '=', self.class9.id)]))

    def test_teacher_name(self):
        # A coordinator names the teacher as typed on the screen.
        resp = self._post(URL, self._body(teacher='Dr. Lpssarah Johnson'), 'lps_coord', 'CoordPass1!')
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(resp.json()['data']['teacher_id'], self.sarah.id)
        self._error(self._post(URL, self._body(), 'lps_coord', 'CoordPass1!'), 400, 'missing_teacher_id')
        self._error(self._post(URL, self._body(teacher='Nobody Known'), 'lps_coord', 'CoordPass1!'), 400,
                    'unknown_teacher')
        # A teacher plans only their own lessons.
        other = self.env['op.faculty'].create({'first_name': 'Lpsother', 'last_name': 'Teacher',
                                               'gender': 'male', 'birth_date': '1980-01-01'})
        self._error(self._post(URL, self._body(teacher_id=other.id)), 403, 'forbidden')

    def test_edit_screen(self):
        data = self._post(URL, self._body()).json()['data']
        url = '%s/%s/update' % (URL, data['id'])
        # Edit: drop "markers" (x), add a recall question, change the duration.
        resp = self._post(url, {'teaching_aids': ['Whiteboard'], 'duration': '1 week',
                                'recall_questions': ['What is a linear equation?', 'What is a variable?']})
        self.assertEqual(resp.status_code, 200, resp.text)
        result = resp.json()['data']
        self.assertEqual([i['text'] for i in result['teaching_aids']], ['Whiteboard'])
        self.assertEqual(len(result['recall_questions']), 2)
        self.assertEqual([i['text'] for i in result['home_work']], ['Practice problems'], 'Lists not sent stay.')
        self.assertEqual((result['duration'], result['topic']), ('1 week', 'Algebra - Linear Equations'))
        self._error(self._post(url, {'home_work': []}), 400, 'missing_home_work')
        self._error(self._post(url, {'plan_date': '20/05/2031'}), 400, 'plan_date_outside_dates')
        self.assertEqual(self._post(url, {'remarks': []}).json()['data']['remarks'], [], 'Remarks may be emptied.')

        # Editing an approved plan sends it back for review.
        self.url_open('%s/%s/review' % (URL, data['id']), headers=self._headers('lps_coord', 'CoordPass1!'),
                      json={'decision': 'approved'})
        self.assertEqual(self.env['bxi.lesson.plan'].browse(data['id']).state, 'approved')
        self.assertEqual(self._post(url, {'topic': 'Linear Equations II'}).json()['data']['state'], 'pending')

        # Only the plan's teacher or a coordinator may edit it.
        self._error(self._post(url, {'topic': 'X'}, 'lps_other', 'OtherPass1!'), 403, 'forbidden')
        coord = self._post(url, {'activities': 'Group work'}, 'lps_coord', 'CoordPass1!')
        self.assertEqual(coord.status_code, 200, coord.text)
        self._error(self._post('%s/999999/update' % URL, {'topic': 'X'}), 404, 'not_found')
