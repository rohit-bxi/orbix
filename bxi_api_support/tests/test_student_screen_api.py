# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The app's Add New Student screen on POST /students and
/students/<id>/update: single name and address, admission number, parent
linking, automatic login, file limits, profile completion and drafts."""
import base64

from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase

PIXEL = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
PDF = base64.b64encode(b'%PDF-1.4\n%test\n').decode()


@tagged('post_install', '-at_install')
class TestStudentScreenApi(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course, cls.batch = cls._create_class('SS')
        cls.other_course, cls.other_batch = cls._create_class('SSX')
        cls.relationship = cls.env['op.parent.relationship'].search([], limit=1) or \
            cls.env['op.parent.relationship'].create({'name': 'Guardian'})
        mail_new_test_user(cls.env, login='ss_office', password='OfficePass1!',
                           groups='base.group_user,openeducat_core.group_op_back_office_admin')

    def _post(self, url, body):
        return self.url_open(url, headers=self._headers('ss_office', 'OfficePass1!'), json=body, method='POST')

    def _get(self, url):
        return self.url_open(url, headers=self._headers('ss_office', 'OfficePass1!'))

    def _body(self, **overrides):
        body = {'name': 'Aarav Kumar Sharma', 'gender': 'm', 'email': 'aarav@ss.test',
                'enrollment': {'course_id': self.course.id, 'batch_id': self.batch.id}}
        body.update(self._student_screen_fields())
        body.update(overrides)
        return body

    def _error(self, resp, status, code):
        self.assertEqual(resp.status_code, status, resp.text)
        self.assertEqual(resp.json()['error']['code'], code)

    # -- create -------------------------------------------------------------------------

    def test_create_from_the_full_screen(self):
        resp = self._post('/api/v1/students', self._body(
            image=PIXEL, blood_group='B+', address='12 MG Road, Indore', admission_number='2024-ST-001',
            status='running', parent={'name': 'Rakesh Sharma', 'relationship_id': self.relationship.id,
                                      'mobile': '+91 98765 43211'},
            aadhaar_number='2345 6789 0124', id_verification={'doc_type': 'aadhaar', 'document': PDF},
            medical_conditions='Peanut allergy',
            documents={'medical_records': [PDF], 'birth_certificate': [{'data': PDF, 'filename': 'birth.pdf'}],
                       'transfer_certificate': [PDF], 'previous_school_certificate': [PDF, PDF]}))
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertEqual((data['first_name'], data['middle_name'], data['last_name']), ('Aarav', 'Kumar', 'Sharma'))
        self.assertEqual(data['name'], 'Aarav Kumar Sharma')
        self.assertEqual(data['address']['street'], '12 MG Road, Indore')
        self.assertEqual(data['admission_number'], '2024-ST-001')
        self.assertEqual(data['medical_conditions'], 'Peanut allergy')
        self.assertEqual(data['health']['medical_notes'], 'Peanut allergy')
        self.assertEqual(data['section']['id'], self.batch.id)
        self.assertIsNone(data['roll_number'], 'The roll number is optional.')
        self.assertEqual(data['status'], 'running')
        self.assertFalse(data['draft'])
        self.assertEqual([(p['name'], p['mobile'], p['relationship']['id']) for p in data['parents']],
                         [('Rakesh Sharma', '+91 98765 43211', self.relationship.id)])
        self.assertEqual(data['verification_status'], 'pending')
        self.assertEqual(data['id_verification']['doc_type'], 'aadhaar')
        self.assertEqual(len(data['documents']['previous_school_certificate']), 2)
        # No account sent: the login is the email, with a one-time password.
        self.assertEqual(data['account']['username'], 'aarav@ss.test')
        self.assertTrue(data['credentials']['one_time_password'])
        completion = data['profile_completion']
        self.assertEqual(completion['missing'], ['roll_number', 'face'])
        self.assertEqual(completion['percent'], 91)
        self.assertEqual(completion['label'], 'Almost done')

    def test_starred_fields_are_required(self):
        before = self.env['op.student'].search_count([])
        for key in ('gender', 'email', 'birth_date', 'phone', 'address', 'admission_number', 'admission_date'):
            self._error(self._post('/api/v1/students', self._body(**{key: ''})), 400, 'missing_%s' % key)
        body = self._body()
        del body['parent']
        self._error(self._post('/api/v1/students', body), 400, 'missing_parent')
        self._error(self._post('/api/v1/students', self._body(name=' ')), 400, 'missing_name')
        self._error(self._post('/api/v1/students', self._body(address={'city': ''})), 400, 'missing_address')
        self._error(self._post('/api/v1/students', self._body(enrollment={'course_id': self.course.id})), 400,
                    'missing_batch_id')
        self._error(self._post('/api/v1/students', self._body(parent={'name': 'X', 'mobile': '9811111111'})), 400,
                    'missing_parent_relationship_id')
        self._error(self._post('/api/v1/students', self._body(status='paused')), 400, 'invalid_status')
        self.assertEqual(self.env['op.student'].search_count([]), before)

        one_word = self._post('/api/v1/students', self._body(name='Aarav', status='finished'))
        self.assertEqual(one_word.status_code, 201, one_word.text)
        data = one_word.json()['data']
        self.assertEqual((data['name'], data['first_name'], data['last_name']), ('Aarav', 'Aarav', None))
        self.assertEqual(data['status'], 'finished', 'status is applied on create.')

    def test_duplicates(self):
        first = self._post('/api/v1/students', self._body(admission_number='DUP-1', parent={
            'name': 'Meena Rao', 'relationship_id': self.relationship.id, 'mobile': '98111 22233'}))
        self.assertEqual(first.status_code, 201, first.text)
        parent_id = first.json()['data']['parents'][0]['id']

        self._error(self._post('/api/v1/students', self._body(email='other@ss.test', admission_number='DUP-1')),
                    409, 'admission_number_taken')
        same_mobile = self._post('/api/v1/students', self._body(email='other@ss.test', parent={
            'name': 'Meena R', 'relationship_id': self.relationship.id, 'mobile': '+91-9811122233'}))
        self._error(same_mobile, 409, 'parent_exists')
        self.assertEqual(same_mobile.json()['error']['existing_parent_id'], parent_id)

        linked = self._post('/api/v1/students', self._body(email='other@ss.test', parent={'parent_id': parent_id}))
        self.assertEqual(linked.status_code, 201, linked.text)
        self.assertEqual(len(self.env['op.parent'].browse(parent_id).student_ids), 2, 'A sibling links the parent.')
        self._error(self._post('/api/v1/students', self._body(email='third@ss.test', parent={'parent_id': 999999})),
                    400, 'invalid_parent_id')

    def test_file_limits(self):
        png = base64.b64decode(PIXEL)
        big_photo = base64.b64encode(png + b'\0' * (1024 * 1024)).decode()
        big_pdf = base64.b64encode(b'%PDF-1.4\n' + b'\0' * (5 * 1024 * 1024)).decode()
        self._error(self._post('/api/v1/students', self._body(image=PDF)), 400, 'invalid_image')
        self._error(self._post('/api/v1/students', self._body(image=big_photo)), 413, 'photo_too_large')
        self._error(self._post('/api/v1/students', self._body(documents={'birth_certificate': [big_pdf]})), 413,
                    'file_too_large')

    # -- update -------------------------------------------------------------------------

    def test_update_name_parent_and_medical(self):
        data = self._post('/api/v1/students', self._body()).json()['data']
        url = '/api/v1/students/%s/update' % data['id']
        sibling = self._post('/api/v1/students', self._body(email='sibling@ss.test')).json()['data']
        other = self.env['op.parent'].browse(sibling['parents'][0]['id'])
        updated = self._post(url, {'name': 'Riya Sen', 'parent': {'parent_id': other.id},
                                   'medical_conditions': 'Asthma', 'address': '5 Lake View'})
        self.assertEqual(updated.status_code, 200, updated.text)
        result = updated.json()['data']
        self.assertEqual((result['name'], result['middle_name']), ('Riya Sen', None))
        self.assertEqual(len(result['parents']), 2, '"parent" adds one; the first parent stays.')
        self.assertEqual(result['medical_conditions'], 'Asthma')
        self.assertEqual(result['address']['street'], '5 Lake View')
        saved = self._post(url, {'draft': True, 'blood_group': 'O+'})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertFalse(saved.json()['data']['draft'], '"Save Draft" on a saved student is an ordinary save.')
        self.assertEqual(saved.json()['data']['blood_group'], 'O+')
        self._error(self._post('/api/v1/students/%s/discard' % data['id'], {}), 400, 'not_a_draft')

    # -- drafts -------------------------------------------------------------------------

    def test_draft_lifecycle(self):
        resp = self._post('/api/v1/students', {
            'draft': True, 'name': 'Dee Raft', 'gender': 'f',
            'enrollment': {'course_id': self.course.id, 'batch_id': self.batch.id, 'roll_number': '4'},
            'documents': {'birth_certificate': [PDF]}})
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        student = self.env['op.student'].with_context(active_test=False).browse(data['id'])
        self.assertTrue(data['draft'])
        self.assertFalse(student.active)
        self.assertFalse(student.course_detail_ids, 'A draft is not enrolled.')
        self.assertFalse(student.user_id, 'A draft has no login.')
        self.assertNotIn('credentials', data)
        self.assertEqual((data['class']['id'], data['section']['id'], data['roll_number']),
                         (self.course.id, self.batch.id, '4'))
        # Name, gender, class, section, roll number, birth certificate: 6 of 22.
        self.assertEqual(data['profile_completion']['percent'], 27)
        self.assertEqual(data['profile_completion']['label'], 'In progress')
        empty = self._post('/api/v1/students', {'draft': True, 'name': 'Just Begun'}).json()['data']
        self.assertEqual(empty['profile_completion']['label'], 'Just started')

        listed = self._get('/api/v1/students?q=Dee Raft').json()
        self.assertEqual(listed['meta']['total'], 0, 'Drafts are left out of the student list.')
        drafts = self._get('/api/v1/students?draft=true&q=Dee Raft').json()['data']['students']
        self.assertEqual([s['id'] for s in drafts], [student.id])
        self.assertEqual(self._get('/api/v1/students/%s' % student.id).status_code, 200)

        self._error(self._post('/api/v1/students', {'draft': True, 'email': 'x@ss.test'}), 400, 'missing_name')
        self._error(self._post('/api/v1/students', {'draft': True, 'name': 'No Login', 'account': {}}), 400,
                    'not_allowed_in_draft')
        self._error(self._post('/api/v1/students', {'draft': 'yes', 'name': 'Bad Flag'}), 400, 'invalid_draft')

        url = '/api/v1/students/%s/update' % student.id
        self._error(self._post(url, {'transfer': {'batch_id': self.other_batch.id}}), 400, 'student_is_draft')
        self._error(self._post(url, {'face': {'enabled': False}}), 400, 'not_allowed_in_draft')
        saved = self._post(url, {'phone': '9822200011', 'active': True, 'status': 'running'})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertTrue(saved.json()['data']['draft'], 'Saving a draft keeps it a draft.')
        self.assertFalse(student.active, '"active" cannot bypass completing the draft.')

        incomplete = self._post(url, {'draft': False, 'email': 'dee@ss.test'})
        self._error(incomplete, 400, 'missing_birth_date')
        student.invalidate_recordset()
        self.assertTrue(student.bxi_is_draft, 'A failed completion changes nothing.')
        self.assertFalse(student.email)

        fields = self._student_screen_fields()
        del fields['phone']
        done = self._post(url, dict(fields, draft=False, email='dee@ss.test'))
        self.assertEqual(done.status_code, 200, done.text)
        result = done.json()['data']
        self.assertFalse(result['draft'])
        self.assertEqual((result['section']['id'], result['roll_number'], result['status']),
                         (self.batch.id, '4', 'running'))
        self.assertTrue(result['credentials']['one_time_password'])
        self.assertTrue(student.active)
        self.assertFalse(student.bxi_draft_batch_id)
        self.assertEqual(student.user_id.login, 'dee@ss.test')
        self.assertEqual(self._get('/api/v1/students?q=Dee Raft').json()['meta']['total'], 1)

    def test_draft_completion_checks_the_class(self):
        data = self._post('/api/v1/students', {'draft': True, 'name': 'No Class'}).json()['data']
        url = '/api/v1/students/%s/update' % data['id']
        self._error(self._post(url, {'enrollment': {'course_id': self.course.id, 'batch_id': self.other_batch.id}}),
                    400, 'batch_course_mismatch')
        body = dict(self._student_screen_fields(), draft=False, email='noclass@ss.test')
        self._error(self._post(url, body), 400, 'missing_course_id')

    def test_discard_draft(self):
        data = self._post('/api/v1/students', {
            'draft': True, 'name': 'Gone Soon', 'documents': {'medical_records': [PDF]}}).json()['data']
        attachment_id = data['documents']['medical_records'][0]['id']
        resp = self._post('/api/v1/students/%s/discard' % data['id'], {})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(self.env['op.student'].with_context(active_test=False).browse(data['id']).exists())
        self.assertFalse(self.env['ir.attachment'].browse(attachment_id).exists())
        self._error(self._post('/api/v1/students/%s/discard' % data['id'], {}), 404, 'not_found')

    def test_notes_and_library_card(self):
        card_type = self.env['op.library.card.type'].create({
            'name': 'SS Card', 'allow_media': 3, 'duration': 7, 'penalty_amt_per_day': 1.0})
        partner = self.env['res.partner'].create({'name': 'Card Holder'})

        def card(kind='student', student=False):
            return self.env['op.library.card'].create({
                'partner_id': partner.id, 'library_card_type_id': card_type.id, 'type': kind,
                'student_id': student and student.id})

        free = card()
        resp = self._post('/api/v1/students', self._body(notes='Sits in the front row.\nNeeds glasses.',
                                                         library_card_id=free.id))
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        student = self.env['op.student'].browse(data['id'])
        self.assertEqual(data['notes'], 'Sits in the front row.\nNeeds glasses.')
        self.assertEqual(data['library_card']['id'], free.id)
        self.assertEqual(free.student_id, student, "The card's own student follows.")
        self.assertEqual(free.partner_id, student.partner_id)

        url = '/api/v1/students/%s/update' % student.id
        other = self._post('/api/v1/students', self._body(email='other.card@ss.test')).json()['data']
        taken = card(student=self.env['op.student'].browse(other['id']))
        self._error(self._post(url, {'library_card_id': taken.id}), 409, 'library_card_taken')
        self._error(self._post(url, {'library_card_id': card(kind='faculty').id}), 400, 'invalid_library_card_id')
        cleared = self._post(url, {'notes': None, 'library_card_id': None}).json()['data']
        self.assertIsNone(cleared['notes'])
        self.assertIsNone(cleared['library_card'])

    def test_edit_screen(self):
        batch_b = self.env['op.batch'].create({
            'name': 'SS Section B', 'code': 'SS-B2', 'course_id': self.course.id,
            'start_date': '2026-01-01', 'end_date': '2027-12-31'})
        data = self._post('/api/v1/students', self._body(parent={
            'name': 'Sanjay Sharma', 'relationship_id': self.relationship.id, 'mobile': '+91 98765 40000'},
            enrollment={'course_id': self.course.id, 'batch_id': self.batch.id, 'roll_number': '7'})).json()['data']
        student = self.env['op.student'].browse(data['id'])
        url = '/api/v1/students/%s/update' % student.id
        father = student.parent_ids

        # The screen sends the parent block back as shown, with a corrected name.
        again = self._post(url, {'parent': {'name': 'Sanjay K Sharma', 'relationship_id': self.relationship.id,
                                            'mobile': '98765 40000'}})
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(student.parent_ids, father, 'The linked parent is corrected, not duplicated.')
        self.assertEqual(father.name.name, 'Sanjay K Sharma')
        moved_phone = self._post(url, {'parent': {'parent_id': father.id, 'mobile': '+91 98765 40001'}})
        self.assertEqual(moved_phone.status_code, 200, moved_phone.text)
        self.assertEqual(moved_phone.json()['data']['parents'][0]['mobile'], '+91 98765 40001')
        self.assertEqual(father.name.phone, '+91 98765 40001')

        # Class / Section / Roll Number.
        roll = self._post(url, {'enrollment': {'course_id': self.course.id, 'batch_id': self.batch.id,
                                               'roll_number': '23'}}).json()['data']
        self.assertEqual((roll['section']['id'], roll['roll_number']), (self.batch.id, '23'))
        self.assertEqual(len(student.course_detail_ids), 1, 'Same section: only the roll number changes.')
        moved = self._post(url, {'enrollment': {'batch_id': batch_b.id, 'roll_number': '4'}}).json()['data']
        self.assertEqual((moved['section']['id'], moved['roll_number']), (batch_b.id, '4'))
        self.assertEqual(student.course_detail_ids.filtered(lambda l: l.batch_id == self.batch).state, 'finished')
        cleared = self._post(url, {'enrollment': {'roll_number': ''}}).json()['data']
        self.assertIsNone(cleared['roll_number'])
        self._error(self._post(url, {'enrollment': {'batch_id': self.other_batch.id, 'course_id': self.course.id}}),
                    400, 'batch_course_mismatch')
        self._error(self._post(url, {'enrollment': {'roll_number': '1'}, 'transfer': {'batch_id': batch_b.id}}),
                    400, 'invalid_enrollment')

        # Status words of the screen.
        inactive = self._post(url, {'status': 'inactive'}).json()['data']
        self.assertEqual((inactive['status'], inactive['status_label']), ('finished', 'Inactive'))
        active = self._post(url, {'status': 'active'}).json()['data']
        self.assertEqual((active['status'], active['status_label']), ('running', 'Active'))
        self._error(self._post(url, {'status': 'paused'}), 400, 'invalid_status')

        # Swapping the parent in the screen's single slot.
        sibling = self._post('/api/v1/students', self._body(email='sib@ss.test')).json()['data']
        mother = self.env['op.parent'].browse(sibling['parents'][0]['id'])
        self._error(self._post(url, {'parent': {'name': 'Someone', 'relationship_id': self.relationship.id,
                                                'mobile': mother.mobile}}), 409, 'parent_exists')
        self._error(self._post(url, {'parent': {'parent_id': father.id, 'mobile': mother.mobile}}), 409,
                    'parent_exists')
        self._error(self._post(url, {'parent': {'parent_id': father.id, 'replace_parent_id': mother.id}}), 400,
                    'invalid_replace_parent_id')
        swapped = self._post(url, {'parent': {'parent_id': mother.id, 'replace_parent_id': father.id}})
        self.assertEqual(swapped.status_code, 200, swapped.text)
        self.assertEqual([p['id'] for p in swapped.json()['data']['parents']], [mother.id])
