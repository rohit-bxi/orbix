# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The Add / Edit Exam screens on /api/v1/academic/exams: one exam across
several sections, kept in step with a draft exam session per section."""
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase

URL = '/api/v1/academic/exams'


@tagged('post_install', '-at_install')
class TestExamScheduleApi(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mail_new_test_user(cls.env, login='es_coordinator', password='CoordPass1!',
                           groups='base.group_user,bxi_academic_management.group_academic_coordinator')
        mail_new_test_user(cls.env, login='es_staff', password='StaffPass1!', groups='base.group_user')
        Subject = cls.env['op.subject']
        cls.english = Subject.create({'name': 'ES English', 'code': 'ES-ENG'})
        cls.hindi = Subject.create({'name': 'ES Hindi', 'code': 'ES-HIN'})
        cls.science = Subject.create({'name': 'ES Science', 'code': 'ES-SCI'})
        cls.art = Subject.create({'name': 'ES Art', 'code': 'ES-ART'})
        cls.class10 = cls.env['op.course'].create({
            'name': 'ES Class 10', 'code': 'ES-10',
            'subject_ids': [(6, 0, (cls.english | cls.hindi | cls.science).ids)]})
        Batch = cls.env['op.batch']
        cls.sec_a, cls.sec_b, cls.sec_c = (Batch.create({
            'name': 'ES 10 %s' % letter, 'code': 'ES-10%s' % letter, 'course_id': cls.class10.id,
            'start_date': '2026-01-01', 'end_date': '2027-12-31'}) for letter in 'ABC')

    def _post(self, url, body, login='es_coordinator', password='CoordPass1!'):
        return self.url_open(url, headers=self._headers(login, password), json=body, method='POST')

    def _get(self, url):
        return self.url_open(url, headers=self._headers('es_coordinator', 'CoordPass1!'))

    def _error(self, resp, status, code):
        self.assertEqual(resp.status_code, status, resp.text)
        self.assertEqual(resp.json()['error']['code'], code)

    def _create(self, **overrides):
        body = {'name': 'Mid-Term Examination', 'start_date': '10/07/2026', 'end_date': '20/07/2026',
                'section_ids': [self.sec_a.id, self.sec_b.id], 'subject_ids': [self.english.id, self.hindi.id]}
        for names, ids in (('sections', 'section_ids'), ('subjects', 'subject_ids')):
            if names in overrides:
                body.pop(ids)
        body.update(overrides)
        return self._post(URL, body)

    def _add_paper(self, session_id, subject, day='2026-07-12'):
        return self._post('/api/v1/exams/sessions/%s/exams' % session_id, {
            'subject_id': subject.id, 'start_time': '%s 04:00:00' % day, 'end_time': '%s 06:00:00' % day,
            'total_marks': 100, 'passing_marks': 35})

    def test_add_exam(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertEqual((data['name'], data['start_date'], data['end_date'], data['status']),
                         ('Mid-Term Examination', '2026-07-10', '2026-07-20', 'draft'))
        self.assertEqual(data['section_ids'], [self.sec_a.id, self.sec_b.id])
        self.assertEqual(data['subject_ids'], [self.english.id, self.hindi.id])
        self.assertEqual(data['exam_type']['name'], 'General', 'A school with no exam type chosen gets General.')
        self.assertEqual(data['papers_progress'], {'set_up': 0, 'expected': 4})
        # One draft session per section, ready for papers on the existing routes.
        self.assertEqual([s['section']['id'] for s in data['sessions']], [self.sec_a.id, self.sec_b.id])
        session = self.env['op.exam.session'].browse(data['sessions'][0]['id'])
        self.assertEqual((session.name, session.course_id, session.state, str(session.start_date)),
                         ('Mid-Term Examination', self.class10, 'draft', '2026-07-10'))
        self.assertTrue(session.exam_code.startswith('EXS/'))
        self.assertNotEqual(data['sessions'][0]['exam_code'], data['sessions'][1]['exam_code'])

        # As typed on the screen.
        typed = self._create(name='Unit Test 1', sections='ES 10 C', subjects='es science, ES-ENG')
        self.assertEqual(typed.status_code, 201, typed.text)
        self.assertEqual(typed.json()['data']['section_ids'], [self.sec_c.id])

        self.assertEqual(self._get(URL + '/%s' % data['id']).json()['data']['id'], data['id'])
        self.assertEqual(self._get(URL + '?section_id=%s' % self.sec_c.id).json()['meta']['total'], 1)
        self.assertEqual(self._get(URL + '?class_id=%s' % self.class10.id).json()['meta']['total'], 2)
        self.assertEqual(self._get(URL + '?subject_id=%s' % self.hindi.id).json()['meta']['total'], 1)
        self.assertEqual(self._get(URL + '?q=mid-term&status=draft').json()['meta']['total'], 1)
        self.assertEqual(self._get(URL + '?date_from=2026-07-21').json()['meta']['total'], 0)
        self._error(self._get(URL + '?status=open'), 400, 'invalid_status')

    def test_required_fields_and_checks(self):
        for key in ('name', 'start_date', 'end_date'):
            body_value = {key: ''}
            self._error(self._create(**body_value), 400, 'missing_%s' % key)
        self._error(self._create(section_ids=[]), 400, 'missing_section_ids')
        self._error(self._create(subject_ids=[]), 400, 'missing_subject_ids')
        self._error(self._create(start_date='31/02/2026'), 400, 'invalid_start_date')
        self._error(self._create(end_date='01/07/2026'), 400, 'invalid_dates')
        self._error(self._create(subject_ids=[self.art.id]), 400, 'subject_not_in_class')
        self._error(self._create(sections=['ES 10 Z']), 400, 'unknown_section')
        self.assertEqual(self.env['op.exam.session'].search_count([('course_id', '=', self.class10.id)]), 0,
                         'A refused exam leaves no session behind.')
        self.assertEqual(self._create().status_code, 201)
        self._error(self._create(section_ids=[self.sec_b.id, self.sec_c.id], start_date='15/07/2026',
                                 end_date='25/07/2026'), 409, 'exam_exists')
        self.assertEqual(self._create(section_ids=[self.sec_c.id]).status_code, 201,
                         'Same name for other sections is a different exam.')
        self._error(self._post(URL, {}, 'es_staff', 'StaffPass1!'), 403, 'forbidden')

    def test_edit_exam(self):
        data = self._create().json()['data']
        url = URL + '/%s/update' % data['id']
        session_a = data['sessions'][0]['id']
        self.assertEqual(self._add_paper(session_a, self.english).status_code, 201)
        self._error(self._add_paper(session_a, self.science), 400, 'subject_not_in_exam')

        # The Edit screen: rename, new dates, add Class 10 C, take Class 10 B off, add Science.
        resp = self._post(url, {'name': 'Mid-Term Exam', 'start_date': '2026-07-11', 'end_date': '21/07/2026',
                                'add_section_ids': [self.sec_c.id], 'remove_section_ids': [self.sec_b.id],
                                'add_subject_ids': [self.science.id]})
        self.assertEqual(resp.status_code, 200, resp.text)
        result = resp.json()['data']
        self.assertEqual(result['section_ids'], [self.sec_a.id, self.sec_c.id])
        self.assertEqual(len(result['subject_ids']), 3)
        self.assertEqual(result['papers_progress'], {'set_up': 1, 'expected': 6})
        sessions = self.env['op.exam.session'].with_context(active_test=False).search(
            [('bxi_schedule_id', '=', data['id'])])
        self.assertEqual(sessions.batch_id, self.sec_a | self.sec_c, 'Class 10 B lost its draft session.')
        self.assertEqual(set(sessions.mapped('name')), {'Mid-Term Exam'})
        self.assertEqual({str(d) for d in sessions.mapped('start_date')}, {'2026-07-11'})

        self._error(self._post(url, {'remove_section_ids': [self.sec_a.id]}), 409, 'section_in_use')
        self._error(self._post(url, {'remove_subject_ids': [self.english.id]}), 409, 'subject_has_papers')
        self._error(self._post(url, {'end_date': '2026-07-11'}), 409, 'papers_outside_dates')
        self._error(self._post(url, {'section_ids': []}), 400, 'missing_section_ids')
        unchanged = self._get(URL + '/%s' % data['id']).json()['data']
        self.assertEqual((unchanged['end_date'], unchanged['section_ids']), ('2026-07-21', [self.sec_a.id, self.sec_c.id]))

        # Status follows the sessions.
        self.env['op.exam.session'].browse(session_a).act_schedule()
        self.assertEqual(self._get(URL + '/%s' % data['id']).json()['data']['status'], 'partly_scheduled')

    def test_delete_exam(self):
        data = self._create().json()['data']
        resp = self._post(URL + '/%s/delete' % data['id'], {})
        self.assertEqual(resp.json()['data'], {'id': data['id'], 'deleted': True})
        self.assertFalse(self.env['op.exam.session'].with_context(active_test=False).search_count(
            [('id', 'in', [s['id'] for s in data['sessions']])]))
        self._error(self._post(URL + '/%s/delete' % data['id'], {}), 404, 'not_found')

        started = self._create(name='Final Examination').json()['data']
        self._add_paper(started['sessions'][0]['id'], self.hindi)
        self._error(self._post(URL + '/%s/delete' % started['id'], {}), 409, 'exam_in_progress')
