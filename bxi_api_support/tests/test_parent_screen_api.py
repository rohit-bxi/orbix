# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The app's Add / Edit Parent screens on POST /parents and
/parents/<id>/update: starred fields, phone, automatic login, linked
students, typed documents, limits, profile completion and drafts."""
import base64

from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase

PIXEL = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
PDF = base64.b64encode(b'%PDF-1.4\n%test\n').decode()


@tagged('post_install', '-at_install')
class TestParentScreenApi(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course, cls.batch = cls._create_class('PS')
        cls.relationship = cls.env['op.parent.relationship'].search([], limit=1) or \
            cls.env['op.parent.relationship'].create({'name': 'Guardian'})
        cls.student = cls._create_student('PS-2024001')
        cls._enroll(cls.student, cls.course, cls.batch)
        cls.sibling = cls._create_student('PS-2024002')
        mail_new_test_user(cls.env, login='ps_office', password='OfficePass1!',
                           groups='base.group_user,openeducat_core.group_op_back_office_admin')

    def _post(self, url, body):
        return self.url_open(url, headers=self._headers('ps_office', 'OfficePass1!'), json=body, method='POST')

    def _get(self, url):
        return self.url_open(url, headers=self._headers('ps_office', 'OfficePass1!'))

    def _body(self, **overrides):
        body = {'name': 'Sanjay Sharma', 'gender': 'm', 'birth_date': '1986-07-02', 'email': 'sanjay@ps.test',
                'phone': '+91 98765 43210', 'address': '789 Indiranagar, Bangalore, Karnataka',
                'relationship_id': self.relationship.id, 'student_ids': [self.student.id]}
        body.update(overrides)
        return body

    def _error(self, resp, status, code):
        self.assertEqual(resp.status_code, status, resp.text)
        self.assertEqual(resp.json()['error']['code'], code)

    def test_create_from_the_full_screen(self):
        resp = self._post('/api/v1/parents', self._body(image=PIXEL, documents={
            'aadhaar_card': [{'data': PDF, 'filename': 'aadhaar.pdf'}], 'pan_card': [PDF], 'id_proof': [PDF, PIXEL]}))
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertEqual((data['name'], data['gender'], data['birth_date']), ('Sanjay Sharma', 'm', '1986-07-02'))
        self.assertEqual((data['phone'], data['mobile']), ('+91 98765 43210', '+91 98765 43210'))
        self.assertEqual(data['address']['street'], '789 Indiranagar, Bangalore, Karnataka')
        self.assertEqual(data['students'], [{
            'id': self.student.id, 'name': self.student.name, 'admission_number': 'PS-2024001',
            'class': {'id': self.course.id, 'name': self.course.display_name},
            'section': {'id': self.batch.id, 'name': self.batch.display_name}, 'roll_number': None,
            'relationship': {'id': self.relationship.id, 'name': self.relationship.display_name}}])
        self.assertEqual(data['documents']['aadhaar_card'][0]['name'], 'aadhaar.pdf')
        self.assertEqual(len(data['documents']['id_proof']), 2)
        document = data['documents']['pan_card'][0]['id']
        self.assertEqual(self._get('/api/v1/parents/%s/documents/%s' % (data['id'], document)).status_code, 200)
        self.assertFalse(data['draft'])
        # No account sent: the login is the email, with a one-time password.
        self.assertEqual(data['account']['username'], 'sanjay@ps.test')
        self.assertTrue(data['credentials']['one_time_password'])
        self.assertEqual(data['profile_completion'], {'percent': 100, 'label': 'Complete', 'missing': []})

    def test_starred_fields_and_limits(self):
        before = self.env['op.parent'].search_count([])
        for key in ('name', 'gender', 'birth_date', 'email', 'address', 'relationship_id', 'student_ids'):
            self._error(self._post('/api/v1/parents', self._body(**{key: ''})), 400, 'missing_%s' % key)
        self._error(self._post('/api/v1/parents', self._body(phone='')), 400, 'missing_mobile')
        big_photo = base64.b64encode(base64.b64decode(PIXEL) + b'\0' * (1024 * 1024)).decode()
        self._error(self._post('/api/v1/parents', self._body(image=big_photo)), 413, 'photo_too_large')
        self._error(self._post('/api/v1/parents', self._body(image=PDF)), 400, 'invalid_image')
        big_pdf = base64.b64encode(b'%PDF-1.4\n' + b'\0' * (5 * 1024 * 1024)).decode()
        self._error(self._post('/api/v1/parents', self._body(documents={'pan_card': [big_pdf]})), 413,
                    'file_too_large')
        self.assertEqual(self.env['op.parent'].search_count([]), before)

        mobile_key = self._post('/api/v1/parents', self._body(phone=None, mobile='9811100000'))
        self.assertEqual(mobile_key.status_code, 201, '"mobile" is still accepted: %s' % mobile_key.text)

    def test_duplicate_mobile(self):
        first = self._post('/api/v1/parents', self._body()).json()['data']
        same = self._post('/api/v1/parents', self._body(email='other@ps.test', phone='98765-43210'))
        self._error(same, 409, 'parent_exists')
        self.assertEqual(same.json()['error']['existing_parent_id'], first['id'])
        other = self._post('/api/v1/parents', self._body(email='other@ps.test', phone='9822233344')).json()['data']
        self._error(self._post('/api/v1/parents/%s/update' % other['id'], {'phone': '+91 98765 43210'}), 409,
                    'parent_exists')
        same_number = self._post('/api/v1/parents/%s/update' % first['id'], {'phone': '9876543210'})
        self.assertEqual(same_number.status_code, 200, 'Re-sending their own number is fine.')

    def test_edit_screen(self):
        data = self._post('/api/v1/parents', self._body(documents={'aadhaar_card': [PDF]})).json()['data']
        url = '/api/v1/parents/%s/update' % data['id']
        kept = data['documents']['aadhaar_card'][0]['id']
        # Link New Student, a new PAN card, and Save Draft on a saved parent.
        resp = self._post(url, {'draft': True, 'student_ids': [self.student.id, self.sibling.id],
                                'documents': {'aadhaar_card': [kept], 'pan_card': [PDF]},
                                'phone': '+91 90000 11111', 'address': '1 New Road'})
        self.assertEqual(resp.status_code, 200, resp.text)
        result = resp.json()['data']
        self.assertFalse(result['draft'], '"Save Draft" on a saved parent is an ordinary save.')
        self.assertEqual([s['admission_number'] for s in result['students']], ['PS-2024001', 'PS-2024002'])
        self.assertEqual([d['id'] for d in result['documents']['aadhaar_card']], [kept])
        self.assertEqual(len(result['documents']['pan_card']), 1)
        self.assertEqual(result['phone'], '+91 90000 11111')
        parent = self.env['op.parent'].browse(data['id'])
        self.assertEqual(parent.name.phone, '+91 90000 11111', 'The contact follows (credentials go there).')
        self._error(self._post(url, {'student_ids': []}), 400, 'missing_student_ids')

    def test_draft_lifecycle(self):
        resp = self._post('/api/v1/parents', {'draft': True, 'name': 'Draft Parent', 'phone': '9833300011',
                                              'documents': {'id_proof': [PDF]}})
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        parent = self.env['op.parent'].with_context(active_test=False).browse(data['id'])
        self.assertTrue(data['draft'])
        self.assertFalse(parent.active)
        self.assertFalse(parent.user_id)
        self.assertEqual(data['students'], [], 'A draft may have no child yet.')
        self.assertEqual(data['profile_completion']['label'], 'In progress')

        self.assertEqual(self._get('/api/v1/parents?q=Draft Parent').json()['meta']['total'], 0)
        drafts = self._get('/api/v1/parents?draft=true&q=Draft Parent').json()['data']['parents']
        self.assertEqual([p['id'] for p in drafts], [parent.id])
        self._error(self._post('/api/v1/parents', {'draft': True, 'name': 'X', 'account': {}}), 400,
                    'not_allowed_in_draft')
        self._error(self._post('/api/v1/parents', {'draft': True}), 400, 'missing_name')

        url = '/api/v1/parents/%s/update' % parent.id
        self._error(self._post(url, {'face': {'enabled': False}}), 400, 'not_allowed_in_draft')
        kept = self._post(url, {'gender': 'f', 'status': 'active'}).json()['data']
        self.assertTrue(kept['draft'])
        self.assertFalse(parent.active, '"status" cannot bypass completing the draft.')
        self._error(self._post(url, {'draft': False}), 400, 'missing_birth_date')
        parent.invalidate_recordset()
        self.assertTrue(parent.bxi_is_draft)

        done = self._post(url, {'draft': False, 'birth_date': '1980-01-01', 'email': 'draft.parent@ps.test',
                                'address': '2 Lake Road', 'relationship_id': self.relationship.id,
                                'student_ids': [self.student.id]})
        self.assertEqual(done.status_code, 200, done.text)
        result = done.json()['data']
        self.assertFalse(result['draft'])
        self.assertEqual(result['status'], 'active')
        self.assertTrue(result['credentials']['one_time_password'])
        self.assertEqual(parent.user_id.login, 'draft.parent@ps.test')
        self._error(self._post('/api/v1/parents/%s/discard' % parent.id, {}), 400, 'not_a_draft')

    def test_discard_draft(self):
        data = self._post('/api/v1/parents', {'draft': True, 'name': 'Gone Parent',
                                              'documents': {'pan_card': [PDF]}}).json()['data']
        attachment = data['documents']['pan_card'][0]['id']
        resp = self._post('/api/v1/parents/%s/discard' % data['id'], {})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(self.env['op.parent'].with_context(active_test=False).browse(data['id']).exists())
        self.assertFalse(self.env['ir.attachment'].browse(attachment).exists())
        self._error(self._post('/api/v1/parents/%s/discard' % data['id'], {}), 404, 'not_found')
