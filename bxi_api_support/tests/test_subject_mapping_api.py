# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The Add / Edit Subject Mapping screens on
/api/v1/academic/subject-mappings."""
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase

URL = '/api/v1/academic/subject-mappings'


@tagged('post_install', '-at_install')
class TestSubjectMappingApi(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mail_new_test_user(cls.env, login='sm_coordinator', password='CoordPass1!',
                           groups='base.group_user,bxi_academic_management.group_academic_coordinator')
        mail_new_test_user(cls.env, login='sm_staff', password='StaffPass1!', groups='base.group_user')
        Subject = cls.env['op.subject']
        cls.maths = Subject.create({'name': 'SM Mathematics', 'code': 'SM-MATH'})
        cls.science = Subject.create({'name': 'SM Science', 'code': 'SM-SCI'})
        cls.art = Subject.create({'name': 'SM Art', 'code': 'SM-ART'})
        Course = cls.env['op.course']
        cls.class9 = Course.create({'name': 'SM Class 9', 'code': 'SM-9',
                                    'subject_ids': [(6, 0, (cls.maths | cls.science).ids)]})
        cls.class10 = Course.create({'name': 'SM Class 10', 'code': 'SM-10'})
        cls.class11 = Course.create({'name': 'SM Class 11', 'code': 'SM-11'})
        Faculty = cls.env['op.faculty']
        cls.sarah = Faculty.create({'first_name': 'Smsarah', 'last_name': 'Johnson', 'gender': 'female',
                                    'birth_date': '1985-01-01'})
        cls.ravi = Faculty.create({'first_name': 'Smravi', 'last_name': 'Kumar', 'gender': 'male',
                                   'birth_date': '1984-01-01'})
        cls.gone = Faculty.create({'first_name': 'Smgone', 'last_name': 'Teacher', 'gender': 'male',
                                   'birth_date': '1980-01-01'})
        cls.gone.active = False
        board = cls.env['bxi.board'].create({'name': 'SM CBSE'})
        Curriculum = cls.env['bxi.curriculum']
        cls.cbse26 = Curriculum.create({
            'name': 'SM CBSE 2026', 'board_id': board.id, 'description': 'x', 'approval_status': 'approved',
            'class_ids': [(6, 0, (cls.class9 | cls.class10).ids)]})
        cls.rejected = Curriculum.create({'name': 'SM Old', 'board_id': board.id, 'description': 'x',
                                          'approval_status': 'rejected'})

    def _post(self, url, body, login='sm_coordinator', password='CoordPass1!'):
        return self.url_open(url, headers=self._headers(login, password), json=body, method='POST')

    def _get(self, url):
        return self.url_open(url, headers=self._headers('sm_staff', 'StaffPass1!'))

    def _error(self, resp, status, code):
        self.assertEqual(resp.status_code, status, resp.text)
        self.assertEqual(resp.json()['error']['code'], code)
        return resp.json()['error']

    def _create(self, **overrides):
        body = {'subject_id': self.maths.id, 'class_id': self.class9.id, 'teacher_id': self.sarah.id,
                'curriculum_id': self.cbse26.id}
        for key in ('subject', 'class', 'teacher'):
            if key in overrides:
                body.pop('%s_id' % key)
        body.update(overrides)
        return self._post(URL, body)

    def test_add_mapping(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertEqual(data['subject'], {'id': self.maths.id, 'name': self.maths.display_name})
        self.assertEqual(data['class'], {'id': self.class9.id, 'name': self.class9.display_name})
        self.assertEqual(data['teacher'], {'id': self.sarah.id, 'name': self.sarah.display_name})
        self.assertEqual(data['curriculum'], {'id': self.cbse26.id, 'name': 'SM CBSE 2026'})
        self.assertEqual((data['subject_id'], data['class_id'], data['teacher_id'], data['curriculum_id']),
                         (self.maths.id, self.class9.id, self.sarah.id, self.cbse26.id))

        # As typed on the screen: names (or codes), and a title before the teacher's name.
        typed = self._create(subject='sm science', **{'class': 'SM-9'}, teacher='Dr. Smsarah Johnson')
        self.assertEqual(typed.status_code, 201, typed.text)
        typed = typed.json()['data']
        self.assertEqual((typed['subject_id'], typed['class_id'], typed['teacher_id']),
                         (self.science.id, self.class9.id, self.sarah.id))

        self.assertEqual(self._get(URL + '/%s' % data['id']).json()['data']['id'], data['id'])
        listed = self._get(URL + '?curriculum_id=%s&subject_id=%s' % (self.cbse26.id, self.science.id)).json()
        self.assertEqual([m['id'] for m in listed['data']['mappings']], [typed['id']])
        self.assertEqual(self._get(URL + '?q=Smsarah').json()['meta']['total'], 2)
        self._error(self._get(URL + '?class_id=nine'), 400, 'invalid_class_id')

    def test_required_fields_and_checks(self):
        for key in ('subject', 'class', 'teacher', 'curriculum'):
            self._error(self._create(**{'%s_id' % key: None}), 400, 'missing_%s_id' % key)
        self._error(self._create(teacher='Nobody Here'), 400, 'unknown_teacher')
        self._error(self._create(subject='Astrology'), 400, 'unknown_subject')
        self._error(self._create(teacher_id=self.gone.id), 400, 'teacher_inactive')
        self._error(self._create(curriculum_id=self.rejected.id), 400, 'curriculum_rejected')
        self._error(self._create(class_id=self.class11.id), 400, 'class_not_in_curriculum')
        self._error(self._create(subject_id=self.art.id), 400, 'subject_not_in_class')
        # A class with no subject list takes any subject.
        self.assertEqual(self._create(subject_id=self.art.id, class_id=self.class10.id).status_code, 201)

        first = self._create().json()['data']
        error = self._error(self._create(teacher_id=self.ravi.id), 409, 'mapping_exists')
        self.assertEqual(error['existing_mapping_id'], first['id'])
        self._error(self._post(URL, {}, 'sm_staff', 'StaffPass1!'), 403, 'forbidden')

    def test_edit_and_delete(self):
        data = self._create().json()['data']
        url = URL + '/%s/update' % data['id']
        resp = self._post(url, {'teacher': 'Smravi Kumar'})
        self.assertEqual(resp.status_code, 200, resp.text)
        result = resp.json()['data']
        self.assertEqual(result['teacher_id'], self.ravi.id)
        self.assertEqual((result['subject_id'], result['class_id']), (self.maths.id, self.class9.id),
                         'Keys not sent are kept.')
        self.assertEqual(self._post(url, {'teacher_id': self.ravi.id}).status_code, 200,
                         'Re-saving the same values is not a duplicate of itself.')
        self._error(self._post(url, {'class_id': self.class11.id}), 400, 'class_not_in_curriculum')
        self._error(self._post(url, {'subject_id': None}), 400, 'missing_subject_id')

        other = self._create(subject_id=self.science.id).json()['data']
        self._error(self._post(URL + '/%s/update' % other['id'], {'subject_id': self.maths.id}), 409,
                    'mapping_exists')

        resp = self._post(URL + '/%s/delete' % data['id'], {})
        self.assertEqual(resp.json()['data'], {'id': data['id'], 'deleted': True})
        self.assertFalse(self.env['bxi.subject.mapping'].browse(data['id']).exists())
        self._error(self._post(URL + '/%s/delete' % data['id'], {}), 404, 'not_found')
