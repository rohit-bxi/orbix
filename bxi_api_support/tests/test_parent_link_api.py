# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The app's Link Student screen: POST /parents/<id>/link-student and
unlink-student, a relationship per linked student, and the student search
that leaves out a parent's children."""
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestParentLinkApi(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course, cls.batch = cls._create_class('PL')
        Relationship = cls.env['op.parent.relationship']
        Relationship._bxi_ensure_defaults()
        cls.father = Relationship.search([('name', '=ilike', 'Father')], limit=1)
        cls.guardian = Relationship.search([('name', '=ilike', 'Guardian')], limit=1)
        cls.aarav = cls._create_student('PL-2024001', first_name='Aarav', last_name='PLSharma')
        madhav_user = mail_new_test_user(cls.env, login='pl_madhav', groups='base.group_portal')
        cls.madhav = cls._create_student('PL-2024002', first_name='Madhav', last_name='PLSharma', user=madhav_user)
        for student in (cls.aarav, cls.madhav):
            cls._enroll(student, cls.course, cls.batch)
        mail_new_test_user(cls.env, login='pl_office', password='OfficePass1!',
                           groups='base.group_user,openeducat_core.group_op_back_office_admin')

    def _post(self, url, body):
        return self.url_open(url, headers=self._headers('pl_office', 'OfficePass1!'), json=body, method='POST')

    def _get(self, url):
        return self.url_open(url, headers=self._headers('pl_office', 'OfficePass1!'))

    def _error(self, resp, status, code):
        self.assertEqual(resp.status_code, status, resp.text)
        self.assertEqual(resp.json()['error']['code'], code)

    def _parent(self, **extra):
        body = dict(self._parent_screen_fields(), name='Sanjay PLSharma', phone='9711078999',
                    relationship_id=self.father.id, student_ids=[self.aarav.id])
        body.update(extra)
        resp = self._post('/api/v1/parents', body)
        self.assertEqual(resp.status_code, 201, resp.text)
        return self.env['op.parent'].browse(resp.json()['data']['id'])

    def test_relationship_choices(self):
        names = {item['name'] for item in self._get('/api/v1/masters/relationships').json()['data']['items']}
        self.assertTrue({'Mother', 'Father', 'Guardian', 'Grandparents', 'Other'} <= names, names)
        self.env['op.parent.relationship']._bxi_ensure_defaults()
        self.assertEqual(self.env['op.parent.relationship'].search_count([('name', '=ilike', 'Guardian')]), 1,
                         'Running it again creates nothing twice.')

    def test_link_with_its_own_relationship(self):
        parent = self._parent()
        url = '/api/v1/parents/%s/link-student' % parent.id

        found = self._get('/api/v1/students?q=PLSharma&exclude_parent_id=%s' % parent.id).json()['data']['students']
        self.assertEqual([(s['id'], s['gr_no']) for s in found], [(self.madhav.id, 'PL-2024002')],
                         'Aarav is already linked: not offered again.')

        resp = self._post(url, {'student_id': self.madhav.id, 'relationship_id': self.guardian.id})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        rows = {s['name']: (s['admission_number'], s['relationship']['id']) for s in data['students']}
        self.assertEqual(rows, {self.aarav.name: ('PL-2024001', self.father.id),
                                self.madhav.name: ('PL-2024002', self.guardian.id)})
        self.assertEqual(data['relationship']['id'], self.father.id, 'The main relationship stays.')
        self.assertIn(self.madhav.user_id, parent.user_id.child_ids, 'The parent login sees the new child.')
        madhav = self._get('/api/v1/students/%s' % self.madhav.id).json()['data']
        self.assertEqual(madhav['parents'][0]['relationship']['id'], self.guardian.id)

        again = self._post(url, {'student_id': self.madhav.id, 'relationship_id': self.father.id})
        self._error(again, 409, 'already_linked')
        self.assertEqual(again.json()['error']['relationship']['id'], self.guardian.id)

        # The student screens' parent block sets the relationship per child too.
        changed = self._post('/api/v1/students/%s/update' % self.madhav.id, {
            'parent': {'parent_id': parent.id, 'relationship_id': self.father.id}})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertFalse(parent.bxi_student_link_ids, 'Same as the main relationship: no separate row.')
        self.assertEqual(parent._bxi_relationship_for(self.madhav), self.father)

    def test_link_errors_and_unlink(self):
        parent = self._parent()
        url = '/api/v1/parents/%s/' % parent.id
        self._error(self._post(url + 'link-student', {'student_id': self.madhav.id}), 400, 'missing_relationship_id')
        self._error(self._post(url + 'link-student', {'relationship_id': self.father.id}), 400, 'missing_student_id')
        self._error(self._post(url + 'link-student', {'student_id': 999999, 'relationship_id': self.father.id}),
                    404, 'not_found')
        self._error(self._post(url + 'link-student', {'student_id': self.madhav.id, 'relationship_id': 999999}),
                    400, 'invalid_relationship_id')
        draft_student = self._post('/api/v1/students', {'draft': True, 'name': 'Draft Kid'}).json()['data']
        self._error(self._post(url + 'link-student', {'student_id': draft_student['id'],
                                                      'relationship_id': self.father.id}), 400, 'student_is_draft')
        draft_parent = self._post('/api/v1/parents', {'draft': True, 'name': 'Draft Dad'}).json()['data']
        self._error(self._post('/api/v1/parents/%s/link-student' % draft_parent['id'], {
            'student_id': self.madhav.id, 'relationship_id': self.father.id}), 400, 'parent_is_draft')

        self._error(self._post(url + 'unlink-student', {'student_id': self.madhav.id}), 400, 'not_linked')
        self._error(self._post(url + 'unlink-student', {'student_id': self.aarav.id}), 400, 'last_student')
        self._post(url + 'link-student', {'student_id': self.madhav.id, 'relationship_id': self.guardian.id})
        self.assertTrue(parent.bxi_student_link_ids)
        resp = self._post(url + 'unlink-student', {'student_id': self.madhav.id})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual([s['id'] for s in resp.json()['data']['students']], [self.aarav.id])
        self.assertFalse(parent.bxi_student_link_ids, 'The relationship with an unlinked child is forgotten.')
        self.assertNotIn(self.madhav.user_id, parent.user_id.child_ids)
