# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportAdminDashboard(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin_user = mail_new_test_user(
            cls.env, login='adm_admin', password='AdminPass1!',
            groups='base.group_user,openeducat_core.group_op_back_office_admin,'
                   'openeducat_fees.group_openeducat_fees_user,'
                   'bxi_school_event_management.group_school_event_coordinator')
        cls.coordinator_user = mail_new_test_user(
            cls.env, login='adm_coord', password='CoordPass1!',
            groups='base.group_user,bxi_academic_management.group_academic_coordinator')
        cls.teacher_user = mail_new_test_user(
            cls.env, login='adm_teacher', password='TeacherPass1!',
            groups='base.group_user,openeducat_core.group_op_faculty')
        cls.parent_user = mail_new_test_user(
            cls.env, login='adm_parent', password='ParentPass1!', groups='base.group_portal')
        cls.faculty = cls._create_faculty(cls.teacher_user, first_name='Adm')

        cls.course, cls.batch = cls._create_class('ADM')
        cls.batch.write({'capacity': 4, 'class_teacher_id': cls.faculty.id})
        cls.other_course, cls.other_batch = cls._create_class('ADMO')
        cls.subject = cls.env['op.subject'].create({'name': 'Adm Maths', 'code': 'ADMMATH'})
        cls.course.subject_ids = cls.subject
        curriculum = cls.env['bxi.curriculum'].create({
            'name': 'Adm Curriculum', 'board_id': cls.env['bxi.board'].create({'name': 'Adm Board'}).id,
            'description': 'Test curriculum',
        })
        cls.env['bxi.subject.mapping'].create({
            'subject_id': cls.subject.id, 'class_id': cls.course.id, 'teacher_id': cls.faculty.id,
            'curriculum_id': curriculum.id,
        })
        cls.env['bxi.timetable.line'].create({
            'timetable_id': cls.env['bxi.timetable'].create({'course_id': cls.course.id, 'batch_id': cls.batch.id}).id,
            'day': 'monday', 'subject_id': cls.subject.id, 'teacher_id': cls.faculty.id,
            'timing_id': cls.env['op.timing'].create({
                'name': 'Adm P1', 'hour': '9', 'minute': '00', 'am_pm': 'am', 'duration': 1.0}).id,
        })

        cls.students = cls.env['op.student']
        for i in range(3):
            student = cls._create_student(f'ADM-00{i}', first_name=f'Pupil{i}', last_name='Adm')
            cls._enroll(student, cls.course, cls.batch)
            cls.students |= student
        cls.other_student = cls._create_student('ADM-099', first_name='Other', last_name='Adm')
        cls._enroll(cls.other_student, cls.other_course, cls.other_batch)
        cls.parent = cls._create_parent(cls.parent_user, cls.students[0], mobile='9000000001')

        # Fees: an overdue unbilled line for students[0] and other_student,
        # a partly paid invoiced line for students[1].
        cls.product = cls.env['product.product'].create({
            'name': 'Adm Tuition', 'type': 'service', 'lst_price': 1000.0,
            'property_account_income_id': cls.income_account.id, 'taxes_id': [(5, 0, 0)],
        })
        cls.category = cls.env['bxi.fee.category'].create({
            'name': 'Adm Tuition', 'code': 'ADM-TUI', 'product_id': cls.product.id,
        })
        cls.structure = cls.env['op.fees.terms'].create({
            'name': 'Adm Structure', 'code': 'ADM-FS1', 'fees_terms': 'fixed_date',
            'line_ids': [(0, 0, {'due_date': fields.Date.today(), 'value': 100.0})],
            'category_line_ids': [(0, 0, {'category_id': cls.category.id, 'amount': 1000.0})],
            'first_due_date': fields.Date.today(),
        })
        past = fields.Date.today() - timedelta(days=10)
        cls.overdue_detail = cls._fee_line(cls.students[0], 1000.0, past)
        cls.other_detail = cls._fee_line(cls.other_student, 400.0, past)
        cls.paid_detail = cls._fee_line(cls.students[1], 500.0, fields.Date.today() + timedelta(days=5))
        invoice = cls._create_posted_invoice(cls.students[1], 500.0, paid=200.0)
        cls.paid_detail.write({'invoice_id': invoice.id, 'state': 'invoice'})

    @classmethod
    def _fee_line(cls, student, amount, due):
        return cls.env['op.student.fees.details'].create({
            'student_id': student.id, 'fees_line_id': cls.structure.line_ids[0].id, 'product_id': cls.product.id,
            'amount': amount, 'discount': 0.0, 'date': due, 'state': 'draft',
        })

    def _admin(self):
        return self._headers('adm_admin', 'AdminPass1!')

    def _get(self, path, headers=None):
        return self.url_open(path, headers=headers or self._admin())

    def _post(self, path, payload, headers=None):
        return self.url_open(path, headers=headers or self._admin(), json=payload, method='POST')

    # -- access -------------------------------------------------------------------

    def test_access(self):
        self.assertEqual(self.url_open('/api/v1/admin/classes').status_code, 401)
        teacher = self._headers('adm_teacher', 'TeacherPass1!')
        parent = self._headers('adm_parent', 'ParentPass1!')
        for path in ('/api/v1/admin/classes', '/api/v1/admin/fees', '/api/v1/admin/fees/by-class',
                     '/api/v1/admin/fees/defaulters', '/api/v1/admin/fee-categories', '/api/v1/admin/events'):
            for headers in (teacher, parent):
                self.assertEqual(self._get(path, headers).status_code, 403, path)
        # Coordinators see classes but only the office adds them.
        coord = self._headers('adm_coord', 'CoordPass1!')
        self.assertEqual(self._get('/api/v1/admin/classes', coord).status_code, 200)
        self.assertEqual(self._post('/api/v1/admin/classes', {'name': 'X', 'code': 'X'}, coord).status_code, 403)
        self.assertEqual(self._get('/api/v1/admin/fees', coord).status_code, 403)

    # -- classes ------------------------------------------------------------------

    def test_class_list(self):
        resp = self._get('/api/v1/admin/classes?q=ADM&expand=sections&sort=code+desc')
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        items = body['data']['items']
        self.assertEqual([i['code'] for i in items], ['ADMO-C', 'ADM-C'])
        adm = items[1]
        self.assertEqual((adm['student_count'], adm['capacity'], adm['fill_percentage']), (3, 4, 75.0))
        self.assertEqual(adm['sections'][0]['class_teacher']['id'], self.faculty.id)
        self.assertEqual(adm['subject_count'], 1)
        summary = body['data']['summary']
        self.assertEqual((summary['classes'], summary['sections'], summary['students']), (2, 2, 4))
        self.assertEqual(summary['sections_without_class_teacher'], 1)
        self.assertEqual(body['meta']['total'], 2)
        self.assertEqual(self._get('/api/v1/admin/classes?sort=bogus').json()['error']['code'], 'invalid_sort')

        year = self.env['op.academic.year'].create({
            'name': 'Adm 2030', 'start_date': '2030-04-01', 'end_date': '2031-03-31'})
        later = self._get(f'/api/v1/admin/classes?q=ADM&academic_year_id={year.id}').json()['data']
        self.assertEqual(later['items'], [], 'No ADM section runs in 2030.')

    def test_class_detail_and_roster(self):
        detail = self._get(f'/api/v1/admin/classes/{self.course.id}').json()['data']
        self.assertEqual(detail['subjects'][0]['teachers'][0]['id'], self.faculty.id)
        section = detail['sections'][0]
        self.assertEqual([(p['subject']['id'], p['teacher']['id']) for p in section['subject_teachers']],
                         [(self.subject.id, self.faculty.id)])
        self.assertEqual(self._get('/api/v1/admin/classes/999999').status_code, 404)

        roster = self._get(f'/api/v1/admin/sections/{self.batch.id}/students').json()['data']
        self.assertEqual(roster['section']['student_count'], 3)
        by_id = {s['id']: s for s in roster['students']}
        self.assertEqual(set(by_id), set(self.students.ids))
        self.assertEqual(by_id[self.students[0].id]['parents'][0]['mobile'], '9000000001')
        self.assertEqual(by_id[self.students[0].id]['gr_no'], 'ADM-000')

    def test_class_create_and_edit(self):
        bad_teacher = self._post('/api/v1/admin/classes', {
            'name': 'Grade 9', 'code': 'G9', 'sections': [{'name': 'A', 'class_teacher_id': 999999}]})
        self.assertEqual(bad_teacher.json()['error']['code'], 'invalid_class_teacher_id')
        clash = self._post('/api/v1/admin/classes', {
            'name': 'Grade 9', 'code': 'G9', 'sections': [{'name': 'A', 'code': 'ADM-B'}]})
        self.assertEqual(clash.json()['error']['code'], 'duplicate_code')
        self.assertFalse(self.env['op.course'].search_count([('code', '=', 'G9')]), 'Nothing is half-saved.')

        resp = self._post('/api/v1/admin/classes', {
            'name': 'Grade 9', 'code': 'G9', 'subject_ids': [self.subject.id], 'evaluation_type': 'normal',
            'sections': [{'name': 'A', 'capacity': 30, 'class_teacher_id': self.faculty.id}, {'name': 'B'}],
        })
        self.assertEqual(resp.status_code, 201, resp.text)
        created = resp.json()['data']
        self.assertEqual([s['name'] for s in created['sections']], ['A', 'B'])
        self.assertEqual(created['sections'][0]['code'], 'G9-A', 'Codes are generated from the class.')
        self.assertEqual(created['capacity'], 30)
        self.assertEqual(self._post('/api/v1/admin/classes', {'name': 'Again', 'code': 'G9'}).json()['error']['code'],
                         'duplicate_code')

        section = self._post('/api/v1/admin/sections', {'class_id': created['id'], 'name': 'C', 'capacity': 25})
        self.assertEqual(section.status_code, 201, section.text)
        section_id = section.json()['data']['id']
        updated = self._post(f'/api/v1/admin/sections/{section_id}/update', {
            'capacity': 28, 'start_date': '2026-06-01', 'end_date': '2027-03-31'}).json()['data']
        self.assertEqual((updated['capacity'], updated['start_date']), (28, '2026-06-01'))
        self.assertEqual(self._post(f'/api/v1/admin/sections/{section_id}/update', {
            'start_date': '2027-06-01', 'end_date': '2027-03-31'}).json()['error']['code'], 'validation_error')
        self.assertEqual(self._post(f'/api/v1/admin/sections/{section_id}/update', {
            'class_id': self.course.id}).json()['error']['code'], 'invalid_class_id')

        archived = self._post(f'/api/v1/admin/classes/{created["id"]}/update', {'active': False, 'name': 'Grade IX'})
        self.assertEqual(archived.json()['data']['name'], 'Grade IX')
        self.assertFalse(archived.json()['data']['active'])
        codes = [i['code'] for i in self._get('/api/v1/admin/classes?active=0').json()['data']['items']]
        self.assertIn('G9', codes)

    # -- fees ---------------------------------------------------------------------

    def test_fee_list(self):
        body = self._get(f'/api/v1/admin/fees?course_id={self.course.id}&sort=amount_pending+desc').json()
        items = body['data']['items']
        self.assertEqual([i['id'] for i in items], [self.overdue_detail.id, self.paid_detail.id])
        self.assertEqual(items[0]['class']['id'], self.course.id)
        self.assertEqual(items[0]['section']['id'], self.batch.id)
        self.assertEqual(items[0]['student']['gr_no'], 'ADM-000')
        summary = body['data']['summary']
        self.assertEqual((summary['total_payable'], summary['amount_paid'], summary['amount_pending']),
                         (1500.0, 200.0, 1300.0))
        self.assertEqual(summary['overdue_amount'], 1000.0)
        self.assertEqual(summary['by_status'], {'overdue': 1, 'partially_paid': 1})

        overdue = self._get('/api/v1/admin/fees?overdue=1&q=ADM').json()['data']
        self.assertEqual({i['id'] for i in overdue['items']}, {self.overdue_detail.id, self.other_detail.id})
        by_category = self._get(f'/api/v1/admin/fees?category_id={self.category.id}&q=Pupil1').json()['data']
        self.assertEqual([i['id'] for i in by_category['items']], [self.paid_detail.id])
        self.assertEqual(self._get('/api/v1/admin/fees?collection_status=nope').json()['error']['code'],
                         'invalid_collection_status')
        self.assertEqual(self._get('/api/v1/admin/fees?due_from=31-01-2026').json()['error']['code'],
                         'invalid_due_from')

    def test_fees_by_class_and_defaulters(self):
        query = f'structure_id={self.structure.id}'
        by_class = self._get(f'/api/v1/admin/fees/by-class?{query}').json()['data']
        rows = {r['class']['id']: r for r in by_class['items']}
        self.assertEqual(rows[self.course.id]['students'], 2)
        self.assertEqual(rows[self.course.id]['collection_percentage'], round(100 * 200 / 1500, 1))
        self.assertEqual(rows[self.other_course.id]['overdue_amount'], 400.0)
        self.assertEqual(by_class['summary']['amount_pending'], 1700.0)
        by_section = self._get(f'/api/v1/admin/fees/by-class?group_by=section&{query}').json()['data']
        self.assertEqual({r['section']['id'] for r in by_section['items']}, {self.batch.id, self.other_batch.id})

        defaulters = self._get(f'/api/v1/admin/fees/defaulters?{query}').json()['data']
        self.assertEqual([d['student']['id'] for d in defaulters['items']], [self.students[0].id, self.other_student.id])
        first = defaulters['items'][0]
        self.assertEqual((first['overdue_amount'], first['days_overdue']), (1000.0, 10))
        self.assertEqual(first['parents'][0]['name'], self.parent_user.name)
        self.assertEqual(defaulters['summary'], {'students': 2, 'overdue_amount': 1400.0,
                                                 'currency': self.env.company.currency_id.name})
        self.assertEqual(self._get(f'/api/v1/admin/fees/defaulters?{query}&min_days=11').json()['data']['items'], [])

    def test_fee_categories(self):
        listed = self._get('/api/v1/admin/fee-categories?q=Adm').json()['data']['items']
        self.assertEqual(listed[0]['structure_count'], 1)
        self.assertEqual(self._post('/api/v1/admin/fee-categories', {'name': 'Lab'}).json()['error']['code'],
                         'missing_product_id')
        resp = self._post('/api/v1/admin/fee-categories', {
            'name': 'Adm Lab Fee', 'product_id': self.product.id, 'default_frequency': 'monthly'})
        self.assertEqual(resp.status_code, 201, resp.text)
        category_id = resp.json()['data']['id']
        self.assertEqual(self._post(f'/api/v1/admin/fee-categories/{category_id}/update', {
            'default_frequency': 'weekly'}).json()['error']['code'], 'invalid_default_frequency')
        updated = self._post(f'/api/v1/admin/fee-categories/{category_id}/update', {
            'is_refundable': False, 'active': False}).json()['data']
        self.assertEqual((updated['is_refundable'], updated['active']), (False, False))
        services = self._get('/api/v1/masters/service-products?q=Adm Tuition').json()['data']['items']
        self.assertEqual([p['id'] for p in services], self.product.ids)

    # -- events -------------------------------------------------------------------

    def _event_payload(self, **vals):
        start = fields.Datetime.now().replace(microsecond=0) + timedelta(days=3)
        return dict({
            'name': 'Adm Sports Day', 'date_begin': fields.Datetime.to_string(start),
            'date_end': fields.Datetime.to_string(start + timedelta(hours=4)), 'category': 'sports_day',
            'target_audience': 'specific_class', 'course_ids': [self.course.id],
            'coordinator_ids': [self.faculty.id], 'seats_limited': True, 'seats_max': 50,
            'requires_permission_slip': True,
        }, **vals)

    def test_event_create_list_and_edit(self):
        self.assertEqual(self._post('/api/v1/admin/events', self._event_payload(category='gala')).json()['error']['code'],
                         'invalid_category')
        unpaid = self._post('/api/v1/admin/events', self._event_payload(is_paid=True))
        self.assertEqual(unpaid.json()['error']['code'], 'validation_error', 'A paid event needs a fee product.')

        resp = self._post('/api/v1/admin/events', self._event_payload())
        self.assertEqual(resp.status_code, 201, resp.text)
        event = self.env['event.event'].browse(resp.json()['data']['id'])
        self.assertEqual(resp.json()['data']['status'], 'upcoming')
        self.assertEqual(event.coordinator_ids, self.faculty)

        Registration = self.env['event.registration']
        signed = Registration.create({'event_id': event.id, 'student_id': self.students[0].id,
                                      'name': 'Pupil0', 'state': 'open', 'permission_slip_signed': True})
        Registration.create({'event_id': event.id, 'student_id': self.students[1].id, 'name': 'Pupil1',
                             'state': 'draft'})
        past = self.env['event.event'].create({
            'name': 'Adm Old Fair', 'date_begin': fields.Datetime.now() - timedelta(days=30),
            'date_end': fields.Datetime.now() - timedelta(days=29), 'event_category': 'other'})

        body = self._get('/api/v1/admin/events?q=Adm&status=upcoming').json()
        self.assertEqual([i['id'] for i in body['data']['items']], event.ids)
        row = body['data']['items'][0]
        self.assertEqual(row['registration_counts'], {'draft': 1, 'open': 1, 'done': 0, 'cancel': 0, 'total': 2})
        self.assertEqual((row['permission_slips_pending'], row['seats_max']), (1, 50))
        self.assertEqual(row['coordinators'][0]['id'], self.faculty.id)
        self.assertEqual(body['data']['summary']['registrations'], 2)
        everything = self._get('/api/v1/admin/events?q=Adm&sort=date_begin+asc').json()['data']
        self.assertEqual([i['id'] for i in everything['items']], [past.id, event.id])
        self.assertEqual(everything['items'][0]['status'], 'past')
        in_range = self._get('/api/v1/admin/events?q=Adm&date_from=%s&date_to=%s' % (
            fields.Date.today() - timedelta(days=30), fields.Date.today())).json()['data']
        self.assertEqual([i['id'] for i in in_range['items']], past.ids)

        detail = self._get(f'/api/v1/admin/events/{event.id}').json()['data']
        reg = {r['id']: r for r in detail['registrations']}[signed.id]
        self.assertEqual((reg['class']['id'], reg['section']['id']), (self.course.id, self.batch.id))

        updated = self._post(f'/api/v1/admin/events/{event.id}/update', {
            'name': 'Adm Sports Day 2026', 'seats_max': 60, 'is_paid': True, 'fee_product_id': self.product.id,
        }).json()['data']
        self.assertEqual((updated['name'], updated['seats_max'], updated['fee_product']['id']),
                         ('Adm Sports Day 2026', 60, self.product.id))
        self.assertEqual(updated['payment'], {'invoiced': 0, 'collected': 0, 'pending': 0, 'not_invoiced': 2})
        self.assertEqual(self._post(f'/api/v1/admin/events/{event.id}/update', {
            'date_begin': 'tomorrow'}).json()['error']['code'], 'invalid_date_begin')

        options = self._get('/api/v1/admin/events/options').json()['data']
        self.assertIn('sports_day', [c['value'] for c in options['categories']])

    def test_event_announcement_and_attendance(self):
        event_id = self._post('/api/v1/admin/events', self._event_payload()).json()['data']['id']
        first = self._post(f'/api/v1/admin/events/{event_id}/post-announcement', {})
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json()['data']['announcement']['state'], 'draft')
        again = self._post(f'/api/v1/admin/events/{event_id}/post-announcement', {})
        self.assertEqual((again.status_code, again.json()['data']['announcement']['id']),
                         (200, first.json()['data']['announcement']['id']))

        Registration = self.env['event.registration']
        confirmed = Registration.create({'event_id': event_id, 'student_id': self.students[0].id,
                                         'name': 'Pupil0', 'state': 'open'})
        unconfirmed = Registration.create({'event_id': event_id, 'student_id': self.students[1].id,
                                           'name': 'Pupil1', 'state': 'draft'})
        refused = self._post(f'/api/v1/admin/events/{event_id}/attendance',
                             {'registration_ids': [confirmed.id, unconfirmed.id]})
        self.assertEqual(refused.json()['error']['code'], 'not_confirmed')
        self.env.invalidate_all()
        self.assertEqual(confirmed.state, 'open', 'A refused batch marks nobody.')

        # The event's duty teacher may take attendance without the coordinator group.
        teacher = self._headers('adm_teacher', 'TeacherPass1!')
        marked = self._post(f'/api/v1/admin/events/{event_id}/attendance',
                            {'registration_ids': [confirmed.id]}, teacher)
        self.assertEqual(marked.status_code, 200, marked.text)
        self.assertEqual(marked.json()['data']['registration_counts']['done'], 1)
        self.env.invalidate_all()
        self.assertEqual(confirmed.state, 'done')
        self._post(f'/api/v1/admin/events/{event_id}/attendance',
                   {'registration_ids': [confirmed.id], 'attended': False})
        self.env.invalidate_all()
        self.assertEqual(confirmed.state, 'open')

        other_event = self.env['event.event'].create({
            'name': 'Adm Other', 'date_begin': fields.Datetime.now() + timedelta(days=5),
            'date_end': fields.Datetime.now() + timedelta(days=6)})
        self.assertEqual(self._post(f'/api/v1/admin/events/{other_event.id}/attendance',
                                    {'registration_ids': [confirmed.id]}).json()['error']['code'], 'not_in_event')
        self.assertEqual(self._post(f'/api/v1/admin/events/{other_event.id}/attendance',
                                    {'registration_ids': [confirmed.id]}, teacher).status_code, 403)
