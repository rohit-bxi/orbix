# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportAcademic(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coordinator_user = mail_new_test_user(
            cls.env, login='academic_api_coordinator',
            groups='base.group_user,bxi_academic_management.group_academic_coordinator',
            password='CoordPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='academic_api_other', groups='base.group_user', password='OtherPass1!')
        cls.board = cls.env['bxi.board'].create({'name': 'API Board'})
        cls.curriculum = cls.env['bxi.curriculum'].create({
            'name': 'API Curriculum', 'board_id': cls.board.id, 'description': 'Test curriculum.',
        })

    def test_curricula_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/academic/curricula').status_code, 401)

    def test_non_coordinator_cannot_approve(self):
        resp = self.url_open(
            f'/api/v1/academic/curricula/{self.curriculum.id}/approve',
            headers=self._headers('academic_api_other', 'OtherPass1!'), method='POST')
        self.assertEqual(resp.status_code, 403)

    def test_coordinator_approval_lifecycle(self):
        headers = self._headers('academic_api_coordinator', 'CoordPass1!')
        approve = self.url_open(
            f'/api/v1/academic/curricula/{self.curriculum.id}/approve', headers=headers, method='POST')
        self.assertEqual(approve.status_code, 200)
        self.assertEqual(approve.json()['data']['approval_status'], 'approved')

        lock = self.url_open(
            f'/api/v1/academic/curricula/{self.curriculum.id}/toggle-lock', headers=headers, method='POST')
        self.assertEqual(lock.status_code, 200)
        self.assertTrue(lock.json()['data']['locked'])

        reject = self.url_open(
            f'/api/v1/academic/curricula/{self.curriculum.id}/reject', headers=headers, method='POST')
        self.assertEqual(reject.status_code, 200)
        self.assertEqual(reject.json()['data']['approval_status'], 'rejected')

    def test_curriculum_not_found(self):
        resp = self.url_open(
            '/api/v1/academic/curricula/999999', headers=self._headers('academic_api_coordinator', 'CoordPass1!'))
        self.assertEqual(resp.status_code, 404)

    def test_reset_curriculum_to_draft(self):
        headers = self._headers('academic_api_coordinator', 'CoordPass1!')
        self.url_open(f'/api/v1/academic/curricula/{self.curriculum.id}/approve', headers=headers, method='POST')
        url = f'/api/v1/academic/curricula/{self.curriculum.id}/reset'
        self.assertEqual(self.url_open(url, headers=self._headers('academic_api_other', 'OtherPass1!'),
                                       method='POST').status_code, 403)
        reset = self.url_open(url, headers=headers, method='POST')
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(reset.json()['data']['approval_status'], 'draft')
        self.assertEqual(self.url_open('/api/v1/academic/curricula/999999/reset', headers=headers,
                                       method='POST').status_code, 404)

    def test_subject_mappings_filters(self):
        course_a = self.env['op.course'].create({'name': 'Map Class A', 'code': 'MAP-A'})
        course_b = self.env['op.course'].create({'name': 'Map Class B', 'code': 'MAP-B'})
        subject = self.env['op.subject'].create({'name': 'Map Science', 'code': 'MAP-S'})
        teacher_a = self.env['op.faculty'].create({
            'first_name': 'Map', 'last_name': 'Alpha', 'gender': 'female', 'birth_date': '1985-01-01'})
        teacher_b = self.env['op.faculty'].create({
            'first_name': 'Map', 'last_name': 'Beta', 'gender': 'male', 'birth_date': '1985-01-01'})
        Mapping = self.env['bxi.subject.mapping']
        first = Mapping.create({'subject_id': subject.id, 'class_id': course_a.id, 'teacher_id': teacher_a.id,
                                'curriculum_id': self.curriculum.id})
        second = Mapping.create({'subject_id': subject.id, 'class_id': course_b.id, 'teacher_id': teacher_b.id,
                                 'curriculum_id': self.curriculum.id})
        headers = self._headers('academic_api_coordinator', 'CoordPass1!')
        by_class = self.url_open(f'/api/v1/academic/subject-mappings?class_id={course_a.id}', headers=headers)
        self.assertEqual(by_class.status_code, 200, by_class.text)
        self.assertEqual([m['id'] for m in by_class.json()['data']['mappings']], [first.id])
        self.assertEqual(by_class.json()['data']['mappings'][0]['teacher'], teacher_a.display_name)
        by_teacher = self.url_open(f'/api/v1/academic/subject-mappings?teacher_id={teacher_b.id}', headers=headers).json()
        self.assertEqual([m['id'] for m in by_teacher['data']['mappings']], [second.id])
        self.assertEqual(by_teacher['meta']['total'], 1)
        mail_new_test_user(self.env, login='academic_api_parent', groups='base.group_portal', password='ParentPass1!')
        self.assertEqual(self.url_open('/api/v1/academic/subject-mappings',
                                       headers=self._headers('academic_api_parent', 'ParentPass1!')).status_code, 403)

    def test_curricula_list_and_detail(self):
        headers = self._headers('academic_api_coordinator', 'CoordPass1!')
        listing = self.url_open('/api/v1/academic/curricula', headers=headers)
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertIn(self.curriculum.id, [c['id'] for c in listing.json()['data']['curricula']])
        detail = self.url_open(f'/api/v1/academic/curricula/{self.curriculum.id}', headers=headers)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['data']['name'], 'API Curriculum')


@tagged('post_install', '-at_install')
class TestCurriculumScreensApi(ApiSupportHttpCase):
    """The Add Curriculum, Edit Curriculum and Assign Classes screens."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mail_new_test_user(cls.env, login='cur_coordinator', password='CoordPass1!',
                           groups='base.group_user,bxi_academic_management.group_academic_coordinator')
        mail_new_test_user(cls.env, login='cur_staff', password='StaffPass1!', groups='base.group_user')
        mail_new_test_user(cls.env, login='cur_portal', password='PortalPass1!', groups='base.group_portal')
        Course = cls.env['op.course']
        cls.class9 = Course.create({'name': 'Cur Class 9', 'code': 'CUR-9'})
        cls.class10 = Course.create({'name': 'Cur Class 10', 'code': 'CUR-10'})
        cls.class11 = Course.create({'name': 'Cur Class 11', 'code': 'CUR-11'})

    def _post(self, url, body, login='cur_coordinator', password='CoordPass1!'):
        return self.url_open(url, headers=self._headers(login, password), json=body, method='POST')

    def _error(self, resp, status, code):
        self.assertEqual(resp.status_code, status, resp.text)
        self.assertEqual(resp.json()['error']['code'], code)

    def _create(self, **extra):
        body = {'name': 'Cur CBSE 2026', 'board': 'CurCBSE', 'description': 'CBSE for 2026',
                'class_id': self.class9.id}
        body.update(extra)
        return self._post('/api/v1/academic/curricula', body)

    def test_add_curriculum(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        board = self.env['bxi.board'].search([('name', '=', 'CurCBSE')])
        self.assertEqual(len(board), 1, 'A typed board that does not exist yet is created.')
        self.assertEqual((data['name'], data['board'], data['board_id'], data['description']),
                         ('Cur CBSE 2026', 'CurCBSE', board.id, 'CBSE for 2026'))
        self.assertEqual(data['class_ids'], [self.class9.id])
        self.assertEqual(data['classes_detail'], [{'id': self.class9.id, 'name': self.class9.display_name}])
        self.assertEqual((data['approval_status'], data['locked']), ('draft', False))

        other = self._create(name='Cur CBSE 2027', board='curcbse', class_ids=[self.class9.id, self.class10.id])
        self.assertEqual(other.status_code, 201, other.text)
        self.assertEqual(other.json()['data']['board_id'], board.id, 'Matched ignoring case, not duplicated.')
        self.assertEqual(len(other.json()['data']['class_ids']), 2)
        boards = self.url_open('/api/v1/masters/boards', headers=self._headers('cur_staff', 'StaffPass1!'))
        self.assertIn(board.id, [b['id'] for b in boards.json()['data']['items']])

    def test_add_curriculum_errors(self):
        before = self.env['bxi.board'].search_count([])
        for key in ('name', 'description'):
            self._error(self._create(**{key: ''}), 400, 'missing_%s' % key)
        body = {'name': 'X', 'description': 'Y', 'class_id': self.class9.id}
        self._error(self._post('/api/v1/academic/curricula', body), 400, 'missing_board')
        self._error(self._create(class_id=None), 400, 'missing_class_ids')
        self._error(self._create(class_ids=[999999]), 400, 'invalid_class_ids')
        self._error(self._create(board_id=999999), 400, 'invalid_board_id')
        self.assertEqual(self._create().status_code, 201)
        self._error(self._create(name='cur cbse 2026'), 409, 'curriculum_exists')
        self._error(self._create(name='Cur Dup', board='CurNewBoard', class_id=999999), 400, 'invalid_class_ids')
        self.assertFalse(self.env['bxi.board'].search([('name', '=', 'CurNewBoard')]))
        dup_board = self._create(board='CurOnlyForDuplicate', name='Cur CBSE 2026')
        self.assertEqual(dup_board.status_code, 201, 'Same name on another board is fine.')
        self.assertEqual(self.env['bxi.board'].search_count([]), before + 2)
        self._error(self._post('/api/v1/academic/curricula', {}, 'cur_staff', 'StaffPass1!'), 403, 'forbidden')
        self._error(self.url_open('/api/v1/academic/curricula', headers=self._headers('cur_portal', 'PortalPass1!')),
                    403, 'forbidden')

    def test_edit_and_assign_classes(self):
        data = self._create().json()['data']
        url = '/api/v1/academic/curricula/%s/update' % data['id']
        edited = self._post(url, {'name': 'Cur CBSE 2024', 'board': 'CurCBSE',
                                  'description': 'Central Board of Secondary Education curriculum for 2024'})
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()['data']['name'], 'Cur CBSE 2024')

        # Assign Classes: the chips are the whole list.
        assigned = self._post(url, {'class_ids': [self.class9.id, self.class10.id]}).json()['data']
        self.assertEqual(sorted(assigned['class_ids']), sorted([self.class9.id, self.class10.id]))
        added = self._post(url, {'add_class_ids': [self.class11.id], 'remove_class_ids': [self.class9.id]})
        self.assertEqual(sorted(added.json()['data']['class_ids']), sorted([self.class10.id, self.class11.id]))
        self._error(self._post(url, {'class_ids': []}), 400, 'missing_class_ids')
        self._error(self._post(url, {'description': ' '}), 400, 'missing_description')
        self._error(self._post('/api/v1/academic/curricula/999999/update', {'name': 'X'}), 404, 'not_found')
        self._create(name='Cur Other')
        self._error(self._post(url, {'name': 'Cur Other'}), 409, 'curriculum_exists')

    def test_lock_and_approval(self):
        data = self._create().json()['data']
        curriculum = self.env['bxi.curriculum'].browse(data['id'])
        url = '/api/v1/academic/curricula/%s/update' % curriculum.id
        curriculum.write({'approval_status': 'approved', 'locked': True})
        self._error(self._post(url, {'class_ids': [self.class10.id]}), 409, 'curriculum_locked')
        self._error(self._post(url, {'board': 'CurICSE'}), 409, 'curriculum_locked')
        self.assertFalse(self.env['bxi.board'].search([('name', '=', 'CurICSE')]), 'Rolled back.')
        same = self._post(url, {'class_ids': [self.class9.id], 'board': 'CurCBSE', 'name': 'Cur Renamed'})
        self.assertEqual(same.status_code, 200, 'Unchanged board and classes may be sent back: %s' % same.text)
        self.assertEqual(same.json()['data']['approval_status'], 'approved', 'A rename keeps the approval.')

        curriculum.locked = False
        moved = self._post(url, {'class_ids': [self.class9.id, self.class10.id]}).json()['data']
        self.assertEqual(moved['approval_status'], 'draft', 'New classes need approving again.')
