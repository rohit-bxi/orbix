# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportPromotion(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.office_user = mail_new_test_user(
            cls.env, login='pro_office', password='OfficePass1!',
            groups='base.group_user,openeducat_core.group_op_back_office_admin')
        cls.coord_user = mail_new_test_user(
            cls.env, login='pro_coord', password='CoordPass1!',
            groups='base.group_user,bxi_academic_management.group_academic_coordinator')
        cls.from_course, cls.from_batch = cls._create_class('PRO5')
        cls.to_course, cls.to_batch = cls._create_class('PRO6')
        cls.year = cls.env['op.academic.year'].create({
            'name': 'Pro 2027-28', 'start_date': '2027-04-01', 'end_date': '2028-03-31'})
        cls.students = cls.env['op.student']
        for i, name in enumerate(('Cara', 'Abe', 'Bea')):
            student = cls._create_student(f'PRO-00{i}', first_name=name, last_name='Pro')
            cls._enroll(student, cls.from_course, cls.from_batch).roll_number = str(10 + i)
            cls.students |= student
        cls.outsider = cls._create_student('PRO-099', first_name='Out', last_name='Sider')
        # Overdue fee for Cara (warning only).
        product = cls.env['product.product'].create({'name': 'Pro Fee', 'type': 'service'})
        structure = cls.env['op.fees.terms'].create({
            'name': 'Pro Structure', 'code': 'PRO-FS', 'fees_terms': 'fixed_date',
            'line_ids': [(0, 0, {'due_date': fields.Date.today(), 'value': 100.0})],
        })
        cls.env['op.student.fees.details'].create({
            'student_id': cls.students[0].id, 'fees_line_id': structure.line_ids[0].id, 'product_id': product.id,
            'amount': 700.0, 'discount': 0.0, 'date': fields.Date.today() - timedelta(days=5), 'state': 'draft',
        })

    def _office(self):
        return self._headers('pro_office', 'OfficePass1!')

    def _post(self, path, payload, headers=None):
        return self.url_open(path, headers=headers or self._office(), json=payload, method='POST')

    def _payload(self, **extra):
        return dict({'from_section_id': self.from_batch.id, 'to_section_id': self.to_batch.id}, **extra)

    def test_access(self):
        coord = self._headers('pro_coord', 'CoordPass1!')
        self.assertEqual(self._post('/api/v1/admin/promotions/preview', self._payload(), coord).status_code, 403)
        self.assertEqual(self._post('/api/v1/admin/promotions', self._payload(), coord).status_code, 403)

    def test_preview_changes_nothing(self):
        resp = self._post('/api/v1/admin/promotions/preview', self._payload(roll_numbers='renumber'))
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertEqual(data['summary']['students'], 3)
        self.assertEqual(data['summary']['ready'], 3)
        self.assertEqual(data['summary']['with_overdue_fees'], 1)
        by_name = {row['student']['name']: row for row in data['students']}
        # Renumbered alphabetically from 1.
        self.assertEqual(by_name['Abe Pro']['new_roll_number'], '1')
        self.assertEqual(by_name['Cara Pro']['new_roll_number'], '3')
        self.assertEqual(by_name['Cara Pro']['warnings'][0]['code'], 'fees_overdue')
        self.assertEqual(self.env['op.student.course'].search_count([('batch_id', '=', self.to_batch.id)]), 0)

    def test_promote_section(self):
        resp = self._post('/api/v1/admin/promotions', self._payload(academic_year_id=self.year.id))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['data']['summary']['moved'], 3)
        for student in self.students:
            lines = student.course_detail_ids
            running = lines.filtered(lambda l: l.state == 'running')
            self.assertEqual(running.batch_id, self.to_batch)
            self.assertEqual(running.academic_years_id, self.year)
            self.assertEqual(lines.filtered(lambda l: l.batch_id == self.from_batch).state, 'finished')
        # Roll numbers kept by default.
        self.assertEqual(sorted(self.students.course_detail_ids.filtered(
            lambda l: l.state == 'running').mapped('roll_number')), ['10', '11', '12'])
        # Nobody left to move.
        self.assertEqual(self._post('/api/v1/admin/promotions', self._payload()).json()['error']['code'],
                         'no_students')

    def test_blocked_student_fails_whole_request(self):
        payload = self._payload(student_ids=(self.students[:1] | self.outsider).ids)
        resp = self._post('/api/v1/admin/promotions', payload)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'promotion_blocked')
        blockers = {row['student']['id']: row['blocker'] for row in resp.json()['data']['students']}
        self.assertEqual(blockers[self.outsider.id], 'not_in_section')
        self.assertEqual(self.students[0].course_detail_ids.filtered(lambda l: l.state == 'running').batch_id,
                         self.from_batch)
        # skip_blocked moves the rest.
        resp = self._post('/api/v1/admin/promotions', dict(payload, skip_blocked=True))
        self.assertEqual(resp.json()['data']['summary']['moved'], 1)
        self.assertEqual(resp.json()['data']['summary']['skipped'], 1)

    def test_roll_number_clash_blocks(self):
        newcomer = self._create_student('PRO-050')
        self._enroll(newcomer, self.to_course, self.to_batch).roll_number = '11'
        rows = self._post('/api/v1/admin/promotions/preview', self._payload()).json()['data']['students']
        self.assertEqual({r['current_roll_number']: r['blocker'] for r in rows}['11'], 'roll_number_taken')
        # Renumbering continues after the section's highest number.
        rows = self._post('/api/v1/admin/promotions/preview', self._payload(roll_numbers='renumber')).json()['data']
        self.assertEqual(sorted(r['new_roll_number'] for r in rows['students']), ['12', '13', '14'])

    def test_graduate(self):
        resp = self._post('/api/v1/admin/promotions', {'from_section_id': self.from_batch.id, 'mode': 'graduate'})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(self.students.course_detail_ids.filtered(lambda l: l.state == 'running'))

    def test_validation(self):
        self.assertEqual(self._post('/api/v1/admin/promotions/preview', {}).json()['error']['code'],
                         'missing_from_section_id')
        self.assertEqual(self._post('/api/v1/admin/promotions/preview', {'from_section_id': self.from_batch.id})
                         .json()['error']['code'], 'missing_to_section_id')
        self.assertEqual(self._post('/api/v1/admin/promotions/preview', self._payload(to_section_id=self.from_batch.id))
                         .json()['error']['code'], 'same_section')
        self.assertEqual(self._post('/api/v1/admin/promotions/preview', self._payload(mode='x'))
                         .json()['error']['code'], 'invalid_mode')
