# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase

# 1x1 transparent PNG.
PIXEL = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='


@tagged('post_install', '-at_install')
class TestBxiApiSupportPeopleManagement(ApiSupportHttpCase):
    """User-management phase 1: the profile fields of the teacher, student
    and parent create/update endpoints."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.department = cls.env['op.department'].create({'name': 'UM Primary', 'code': 'UMP'})
        cls.course, cls.batch = cls._create_class('UM')
        cls.course.department_id = cls.department
        cls.batch_b = cls.env['op.batch'].create({
            'name': 'UM Section B', 'code': 'UM-B2', 'course_id': cls.course.id,
            'start_date': '2026-01-01', 'end_date': '2027-12-31',
        })
        cls.other_course, cls.other_batch = cls._create_class('UMX')
        cls.subject = cls.env['op.subject'].create({'name': 'UM Physics', 'code': 'UMPHY'})
        cls.job = cls.env['hr.job'].create({'name': 'UM Senior Teacher'})
        cls.duty = cls.env['bxi.staff.responsibility'].create({'name': 'UM Exam Coordinator'})
        cls.office_user = mail_new_test_user(
            cls.env, login='um_office', groups='base.group_user,openeducat_core.group_op_back_office_admin',
            password='OfficePass1!')
        cls.parent_user = mail_new_test_user(
            cls.env, login='um_parent', groups='base.group_portal', password='ParentPass1!')
        cls.relationship = cls.env['op.parent.relationship'].search([], limit=1) or \
            cls.env['op.parent.relationship'].create({'name': 'Guardian'})

    def _office(self):
        return self._headers('um_office', 'OfficePass1!')

    def _post(self, url, body):
        return self.url_open(url, headers=self._office(), json=body)

    def _teacher_body(self, **overrides):
        body = {'first_name': 'Uma', 'last_name': 'Mentor', 'gender': 'female', 'birth_date': '1988-02-03'}
        body.update(overrides)
        return body

    def _student_body(self, **overrides):
        body = {'first_name': 'Sam', 'last_name': 'Pupil', 'gender': 'm', 'email': 'sam.pupil@um.test',
                'enrollment': {'course_id': self.course.id, 'batch_id': self.batch.id, 'roll_number': '7'},
                'account': {'username': 'sam.pupil', 'password': 'SamPupil99'}}
        body.update(overrides)
        return body

    # -- teachers -----------------------------------------------------------------------

    def test_teacher_create_with_full_profile(self):
        resp = self._post('/api/v1/teachers', self._teacher_body(
            email='uma.mentor@um.test', image=f'data:image/png;base64,{PIXEL}',
            address={'street': '1 School Rd', 'city': 'Pune', 'zip': '411001'},
            emergency_contact={'name': 'Ravi Mentor', 'phone': '9800011122', 'relation': 'Spouse'},
            highest_qualification='M.Sc', specialization_subject_id=self.subject.id, subject_ids=[self.subject.id],
            years_of_experience='8', previous_school='Old School', certifications='B.Ed, CTET',
            assignments={'batch_ids': [self.batch.id]},
            workload={'max_weekly_periods': 24, 'timetable_auto_assign': True},
            designation_id=self.job.id, responsibility_ids=[self.duty.id], status='on_leave', notes='Prefers mornings'))
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertTrue(data['has_photo'])
        self.assertEqual(data['address']['city'], 'Pune')
        self.assertEqual(data['emergency_contact'], {'name': 'Ravi Mentor', 'phone': '9800011122', 'relation': 'Spouse'})
        self.assertEqual(data['specialization']['id'], self.subject.id)
        self.assertEqual(data['certifications'], 'B.Ed, CTET')
        self.assertEqual([c['id'] for c in data['assignments']['classes']], [self.course.id],
                         'A section brings its class along.')
        self.assertEqual([b['id'] for b in data['assignments']['sections']], [self.batch.id])
        self.assertEqual(data['workload']['max_weekly_periods'], 24)
        self.assertEqual(data['workload']['assigned_periods'], 0)
        self.assertEqual(data['workload']['remaining_periods'], 24)
        self.assertTrue(data['workload']['timetable_auto_assign'])
        self.assertEqual(data['designation']['id'], self.job.id)
        self.assertEqual([r['id'] for r in data['responsibilities']], [self.duty.id])
        self.assertEqual(data['status'], 'on_leave')
        self.assertEqual(data['notes'], 'Prefers mornings')

        photo = self.url_open(f"/api/v1/teachers/{data['id']}/photo", headers=self._office())
        self.assertEqual(photo.status_code, 200)
        on_leave = self.url_open('/api/v1/teachers?status=on_leave', headers=self._office()).json()['data']['teachers']
        self.assertEqual([t['id'] for t in on_leave], [data['id']])

    def test_teacher_update_and_validation(self):
        created = self._post('/api/v1/teachers', self._teacher_body(
            emergency_contact={'name': 'First Contact', 'phone': '1'})).json()['data']
        url = f"/api/v1/teachers/{created['id']}/update"
        faculty = self.env['op.faculty'].browse(created['id'])
        contact = faculty.emergency_contact

        updated = self._post(url, {'emergency_contact': {'phone': '2', 'relation': 'Brother'}, 'status': 'resigned',
                                   'assignments': {'course_ids': [self.other_course.id]}})
        self.assertEqual(updated.status_code, 200, updated.text)
        data = updated.json()['data']
        self.assertEqual(data['emergency_contact'], {'name': 'First Contact', 'phone': '2', 'relation': 'Brother'})
        self.assertEqual(faculty.emergency_contact, contact, 'The same contact person is updated, not replaced.')
        self.assertEqual(data['status'], 'resigned')
        self.assertEqual([c['id'] for c in data['assignments']['classes']], [self.other_course.id])

        removed = self._post(url, {'emergency_contact': None}).json()['data']
        self.assertIsNone(removed['emergency_contact'])

        for body, code in (
            ({'status': 'retired'}, 'invalid_status'),
            ({'designation_id': 999999}, 'invalid_designation_id'),
            ({'workload': {'max_weekly_periods': -1}}, 'invalid_max_weekly_periods'),
            ({'gender': 'm'}, 'invalid_gender'),
            ({'image': 'not base64!'}, 'invalid_image'),
            ({'emergency_contact': {'phone': '3'}}, 'missing_emergency_contact_name'),
        ):
            resp = self._post(url, body)
            self.assertEqual(resp.status_code, 400, body)
            self.assertEqual(resp.json()['error']['code'], code, body)

        not_an_image = self._post(url, {'image': 'aGVsbG8='})
        self.assertEqual(not_an_image.status_code, 400, 'base64 that is not an image is rejected by the field')

    def test_teacher_email_must_be_unique(self):
        self._post('/api/v1/teachers', self._teacher_body(email='dup@um.test'))
        resp = self._post('/api/v1/teachers', self._teacher_body(first_name='Other', email='DUP@um.test'))
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error']['code'], 'email_taken')

    def test_teacher_create_rolls_back_on_bad_emergency_contact(self):
        before = self.env['op.faculty'].search_count([])
        resp = self._post('/api/v1/teachers', self._teacher_body(emergency_contact='Ravi'))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.env['op.faculty'].search_count([]), before)

    # -- students -----------------------------------------------------------------------

    def test_student_create_requires_enrolment_and_email(self):
        for overrides, code in (
            ({'email': ''}, 'missing_email'),
            ({'enrollment': None}, 'missing_enrollment'),
            ({'enrollment': {'course_id': self.course.id, 'batch_id': self.batch.id}}, 'missing_roll_number'),
            ({'enrollment': {'course_id': self.course.id, 'roll_number': '1'}}, 'missing_batch_id'),
            ({'enrollment': {'course_id': self.course.id, 'batch_id': self.other_batch.id, 'roll_number': '1'}},
             'batch_course_mismatch'),
            ({'blood_group': 'Z+'}, 'invalid_blood_group'),
        ):
            resp = self._post('/api/v1/students', self._student_body(**overrides))
            self.assertEqual(resp.status_code, 400, overrides)
            self.assertEqual(resp.json()['error']['code'], code, overrides)

        created = self._post('/api/v1/students', self._student_body(image=PIXEL, address={'city': 'Pune'}))
        self.assertEqual(created.status_code, 201, created.text)
        data = created.json()['data']
        self.assertEqual(data['roll_number'], '7')
        self.assertEqual(data['section']['id'], self.batch.id)
        self.assertEqual(data['status'], 'running')
        self.assertEqual(data['department']['id'], self.department.id)
        self.assertEqual(data['address']['city'], 'Pune')
        self.assertTrue(data['has_photo'])

        twice = self._post('/api/v1/students', self._student_body(
            enrollment={'course_id': self.course.id, 'batch_id': self.batch.id, 'roll_number': '8'},
            account={'username': 'sam.twice', 'password': 'SamTwice99'}))
        self.assertEqual(twice.json()['error']['code'], 'email_taken')

    def test_student_transfer_and_status(self):
        student_id = self._post('/api/v1/students', self._student_body()).json()['data']['id']
        url = f'/api/v1/students/{student_id}/update'
        student = self.env['op.student'].browse(student_id)

        no_roll = self._post(url, {'blood_group': 'O+', 'transfer': {'batch_id': self.batch_b.id}})
        self.assertEqual(no_roll.json()['error']['code'], 'missing_roll_number')
        self.assertFalse(student.blood_group, 'A rejected transfer rolls back the rest of the update.')

        moved = self._post(url, {'blood_group': 'O+', 'transfer': {'batch_id': self.batch_b.id, 'roll_number': '21'}})
        self.assertEqual(moved.status_code, 200, moved.text)
        data = moved.json()['data']
        self.assertEqual(data['section']['id'], self.batch_b.id)
        self.assertEqual(data['roll_number'], '21')
        self.assertEqual(data['blood_group'], 'O+')
        old_line = student.course_detail_ids.filtered(lambda l: l.batch_id == self.batch)
        self.assertEqual(old_line.state, 'finished', 'The old section keeps its history.')

        back = self._post(url, {'transfer': {'batch_id': self.batch.id}}).json()['data']
        self.assertEqual(back['section']['id'], self.batch.id)
        self.assertEqual(back['roll_number'], '7', 'Going back reopens the earlier enrolment.')
        self.assertEqual(len(student.course_detail_ids), 2)

        wrong_class = self._post(url, {'transfer': {'batch_id': self.batch.id, 'course_id': self.other_course.id}})
        self.assertEqual(wrong_class.json()['error']['code'], 'batch_course_mismatch')

        finished = self._post(url, {'status': 'finished'}).json()['data']
        self.assertEqual(finished['status'], 'finished')
        running = self._post(url, {'status': 'running'}).json()['data']
        self.assertEqual(running['status'], 'running')
        self.assertEqual(running['section']['id'], self.batch.id,
                         'Running again reopens the section just finished, not the newest enrolment.')
        self.assertEqual(student.course_detail_ids.filtered(lambda l: l.state == 'running').batch_id, self.batch)
        self._post(url, {'status': 'finished'})
        self.assertEqual(self._post(url, {'status': 'expelled'}).json()['error']['code'], 'invalid_status')

    # -- parents ------------------------------------------------------------------------

    def test_parent_profile_status_and_derived_classes(self):
        student = self._create_student('UM-P1')
        self._enroll(student, self.course, self.batch)
        resp = self._post('/api/v1/parents', {
            'name': 'Pia Parent', 'mobile': '9800099911', 'relationship_id': self.relationship.id,
            'student_ids': [student.id], 'image': PIXEL,
            'account': {'username': 'pia.parent', 'password': 'PiaParent99'}})
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertTrue(data['has_photo'])
        self.assertEqual(data['status'], 'active')
        self.assertEqual([d['id'] for d in data['departments']], [self.department.id])
        self.assertEqual(data['classes'][0]['section']['id'], self.batch.id)

        url = f"/api/v1/parents/{data['id']}/update"
        inactive = self._post(url, {'status': 'inactive', 'name': 'Pia P.'}).json()['data']
        self.assertEqual(inactive['status'], 'inactive')
        self.assertEqual(inactive['name'], 'Pia P.')
        self.assertEqual(self._post(url, {'status': 'gone'}).json()['error']['code'], 'invalid_status')
        self.assertEqual(self._post(url, {'status': 'active'}).json()['data']['status'], 'active')
        photo = self.url_open(f"/api/v1/parents/{data['id']}/photo", headers=self._office())
        self.assertEqual(photo.status_code, 200)

    def test_parent_create_login_failure_rolls_back(self):
        student = self._create_student('UM-P2')
        before = self.env['op.parent'].search_count([])
        resp = self._post('/api/v1/parents', {
            'name': 'No Email', 'mobile': '9800099922', 'relationship_id': self.relationship.id,
            'student_ids': [student.id], 'account': {'username': 'admin', 'password': 'TakenLogin99'}})
        self.assertEqual(resp.status_code, 409, 'The username is taken: nothing is created.')
        self.assertEqual(self.env['op.parent'].search_count([]), before)

    # -- masters and access -------------------------------------------------------------

    def test_masters_and_access(self):
        designations = self.url_open('/api/v1/masters/designations', headers=self._office()).json()['data']['items']
        self.assertIn(self.job.id, [d['id'] for d in designations])
        duties = self.url_open('/api/v1/masters/staff-responsibilities', headers=self._office()).json()['data']['items']
        self.assertIn(self.duty.id, [d['id'] for d in duties])
        parent = self._headers('um_parent', 'ParentPass1!')
        self.assertEqual(self.url_open('/api/v1/masters/designations', headers=parent).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/teachers', headers=parent, json=self._teacher_body()).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/teachers/999999/photo', headers=self._office()).status_code, 404)

    def test_parent_detail(self):
        student = self._create_student('UM-P2')
        self._enroll(student, self.course, self.batch)
        parent_id = self._post('/api/v1/parents', {
            'name': 'Dev Parent', 'mobile': '9800099922', 'relationship_id': self.relationship.id,
            'student_ids': [student.id], 'account': {'username': 'dev.parent', 'password': 'DevParent99'},
        }).json()['data']['id']
        resp = self.url_open(f'/api/v1/parents/{parent_id}', headers=self._office())
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertEqual((data['id'], data['name'], data['mobile']), (parent_id, 'Dev Parent', '9800099922'))
        self.assertEqual(data['classes'][0]['section']['id'], self.batch.id)
        self.assertIn('account', data)
        # Parents can't read other people's records through the staff directory.
        self.assertEqual(self.url_open(f'/api/v1/parents/{parent_id}',
                                       headers=self._headers('um_parent', 'ParentPass1!')).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/parents/999999', headers=self._office()).status_code, 404)

    # -- every form field (2026-11-18) ----------------------------------------------------

    def _masters(self):
        title = self.env['res.partner.title'].create({'name': 'UM Doctor', 'shortcut': 'Dr.'})
        category = self.env['op.category'].create({'name': 'UM General', 'code': 'UMGEN'})
        state = self.env.ref('base.state_in_mh')
        return title, category, state

    def test_student_update_every_field_reads_back(self):
        title, category, state = self._masters()
        student_id = self._post('/api/v1/students', self._student_body()).json()['data']['id']
        student = self.env['op.student'].browse(student_id)
        parent = self._create_parent(self.parent_user, self._create_student('UM-SIB'))
        url = f'/api/v1/students/{student_id}/update'
        health = {'is_allergy': True, 'allergy': 'Peanuts', 'chronic_conditions': 'Asthma',
                  'disabilities': 'None', 'dietary_restrictions': 'Vegetarian', 'primary_physician': 'Dr Rao',
                  'physician_contact': '9800000001', 'insurance_provider': 'LIC', 'insurance_policy_no': 'P-1',
                  'medical_notes': 'Inhaler in bag'}
        resp = self._post(url, {
            'middle_name': 'K', 'title_id': title.id, 'nick_name': 'Sammy', 'lang': 'en_US', 'religion': 'hindu',
            'category_id': category.id, 'visa_info': 'N/A', 'trait': 'Curious', 'mode_of_transport': 'school_bus',
            'enrollment_status': 'active', 'scolar_number': 'SC-9', 'other_sibling': 'Ria, class 3',
            'pickup_person': 'Grandfather', 'special_needs_and_abilities': 'Chess', 'id_number': 'ID-77',
            'admission_date': '2026-06-01', 'nationality_id': self.env.ref('base.in').id,
            'address': {'street': '2 Lane', 'state_id': state.id, 'country_id': self.env.ref('base.in').id},
            'parent_ids': [parent.id], 'emergency_contact': {'name': 'Uncle Raj', 'phone': '9800000002'},
            'health': health, 'documents': {'birth_certificate': [{'data': PIXEL, 'filename': 'birth.png'}],
                                            'medical_records': [PIXEL]},
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        expected = {
            'middle_name': 'K', 'nick_name': 'Sammy', 'lang': 'en_US', 'religion': 'hindu', 'visa_info': 'N/A',
            'trait': 'Curious', 'mode_of_transport': 'school_bus', 'enrollment_status': 'active',
            'scolar_number': 'SC-9', 'other_sibling': 'Ria, class 3', 'pickup_person': 'Grandfather',
            'special_needs_and_abilities': 'Chess', 'id_number': 'ID-77', 'admission_date': '2026-06-01',
            'first_name': 'Sam', 'last_name': 'Pupil', 'active': True,
        }
        self.assertEqual({key: data[key] for key in expected}, expected)
        self.assertEqual(data['title']['id'], title.id)
        self.assertEqual(data['category']['id'], category.id)
        self.assertEqual(data['nationality']['id'], self.env.ref('base.in').id)
        self.assertEqual(data['address']['state']['id'], state.id)
        self.assertEqual([p['id'] for p in data['parents']], [parent.id])
        self.assertEqual(data['emergency_contact'], {'name': 'Uncle Raj', 'phone': '9800000002'})
        self.assertEqual(data['health'], health)
        self.assertEqual(data['documents']['birth_certificate'][0]['name'], 'birth.png')
        self.assertEqual(len(data['documents']['medical_records']), 1)
        self.assertEqual(data['documents']['transfer_certificate'], [])

        fetched = self.url_open(f'/api/v1/students/{student_id}', headers=self._office())
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json()['data']['nick_name'], 'Sammy')

        kept = data['documents']['birth_certificate'][0]['id']
        removed = data['documents']['medical_records'][0]['id']
        download = self.url_open(f'/api/v1/students/{student_id}/documents/{kept}', headers=self._office())
        self.assertEqual(download.status_code, 200)
        self.assertEqual(self.url_open(f'/api/v1/students/{student_id}/documents/{kept}',
                                       headers=self._headers('um_parent', 'ParentPass1!')).status_code, 403)

        cleared = self._post(url, {
            'nick_name': None, 'category_id': None, 'title_id': '', 'parent_ids': [], 'emergency_contact': None,
            'health': {'allergy': None, 'is_allergy': False}, 'active': False,
            'documents': {'birth_certificate': [kept, PIXEL], 'medical_records': []},
        }).json()['data']
        self.assertIsNone(cleared['nick_name'])
        self.assertIsNone(cleared['category'])
        self.assertIsNone(cleared['title'])
        self.assertEqual(cleared['parents'], [])
        self.assertIsNone(cleared['emergency_contact'])
        self.assertIsNone(cleared['health']['allergy'])
        self.assertEqual(cleared['health']['chronic_conditions'], 'Asthma', 'Keys not sent are kept.')
        self.assertFalse(cleared['active'])
        self.assertEqual(len(cleared['documents']['birth_certificate']), 2)
        self.assertIn(kept, [d['id'] for d in cleared['documents']['birth_certificate']])
        self.assertEqual(cleared['documents']['medical_records'], [])
        self.assertFalse(self.env['ir.attachment'].browse(removed).exists(), 'A removed file is deleted.')
        self.assertEqual(self.url_open(f'/api/v1/students/{student_id}/documents/{removed}',
                                       headers=self._office()).status_code, 404)
        self.assertFalse(student.active)
        self.assertEqual(self.url_open(f'/api/v1/students/{student_id}', headers=self._office()).status_code, 200,
                         'An archived student can still be opened.')

    def test_student_update_validation(self):
        student_id = self._post('/api/v1/students', self._student_body()).json()['data']['id']
        url = f'/api/v1/students/{student_id}/update'
        student = self.env['op.student'].browse(student_id)
        for body, code in (
            ({'religion': 'pastafarian'}, 'invalid_religion'),
            ({'lang': 'xx_XX'}, 'invalid_lang'),
            ({'category_id': 999999}, 'invalid_category_id'),
            ({'birth_date': '31-12-2010'}, 'invalid_birth_date'),
            ({'nick_name': {'a': 1}}, 'invalid_nick_name'),
            ({'active': 'no'}, 'invalid_active'),
            ({'first_name': None}, 'missing_first_name'),
            ({'gender': ''}, 'missing_gender'),
            ({'email': None}, 'missing_email'),
            ({'health': 'fine'}, 'invalid_health'),
            ({'documents': {'passport': [PIXEL]}}, 'invalid_documents'),
            ({'documents': {'birth_certificate': 'x'}}, 'invalid_documents'),
            ({'documents': {'birth_certificate': ['aGVsbG8=']}}, 'invalid_file_type'),
            ({'nick_name': 'Rolled', 'documents': {'birth_certificate': [999999]}}, 'invalid_documents'),
        ):
            resp = self._post(url, body)
            self.assertEqual(resp.status_code, 400, body)
            self.assertEqual(resp.json()['error']['code'], code, body)
        self.assertFalse(student.nick_name, 'A rejected document list rolls back the rest of the update.')
        # Keys of the other kinds of person used to reach the model and 500.
        for body in ({'relationship_id': self.relationship.id}, {'main_department_id': self.department.id}):
            self.assertEqual(self._post(url, body).status_code, 200, body)
        self.assertEqual(self.url_open('/api/v1/students/999999', headers=self._office()).status_code, 404)

    def test_teacher_update_every_field_reads_back(self):
        title, category, state = self._masters()
        faculty_id = self._post('/api/v1/teachers', self._teacher_body()).json()['data']['id']
        url = f'/api/v1/teachers/{faculty_id}/update'
        india = self.env.ref('base.in').id
        resp = self._post(url, {
            'title_id': title.id, 'lang': 'en_US', 'religion': 'sikh', 'category_id': category.id, 'cast': 'General',
            'visa_info': 'Work visa', 'nationality': india, 'main_department_id': self.department.id,
            'allowed_department_ids': [self.department.id], 'joining_date': '2025-04-01',
            'official_address': {'street': 'School Campus', 'city': 'Pune', 'state_id': state.id, 'country_id': india},
            'postal_address': {'city': 'Mumbai'}, 'regional_address': {'zip': '411002'},
            'health': {'is_allergy': True, 'allergy': 'Dust', 'medical_notes': 'None'},
            'workload': {'available_days': ['monday', 'friday']},
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertEqual(data['title']['id'], title.id)
        self.assertEqual((data['lang'], data['religion'], data['cast'], data['visa_info']),
                         ('en_US', 'sikh', 'General', 'Work visa'))
        self.assertEqual(data['category']['id'], category.id)
        self.assertEqual(data['department']['id'], self.department.id)
        self.assertEqual([d['id'] for d in data['allowed_departments']], [self.department.id])
        self.assertEqual(data['official_address']['city'], 'Pune')
        self.assertEqual(data['official_address']['state']['id'], state.id)
        self.assertEqual(data['postal_address']['city'], 'Mumbai')
        self.assertEqual(data['regional_address']['zip'], '411002')
        self.assertIsNone(data['address']['city'], 'The main address is separate.')
        self.assertEqual(data['health']['allergy'], 'Dust')
        self.assertEqual(data['workload']['available_days'], ['monday', 'friday'])
        self.assertEqual(data['first_name'], 'Uma')
        self.assertTrue(data['active'])

        cleared = self._post(url, {'nationality': None, 'allowed_department_ids': [], 'active': False,
                                   'official_address': {'state_id': None}}).json()['data']
        self.assertIsNone(cleared['nationality'])
        self.assertEqual(cleared['allowed_departments'], [])
        self.assertIsNone(cleared['official_address']['state'])
        self.assertEqual(cleared['official_address']['city'], 'Pune')
        self.assertFalse(cleared['active'])

        for body, code in (
            ({'workload': {'available_days': ['sunday']}}, 'invalid_available_days'),
            ({'official_address': 'Pune'}, 'invalid_official_address'),
            ({'postal_address': {'country_id': 999999}}, 'invalid_country_id'),
            ({'birth_date': None}, 'missing_birth_date'),
            ({'religion': 'none'}, 'invalid_religion'),
        ):
            resp = self._post(url, body)
            self.assertEqual(resp.status_code, 400, body)
            self.assertEqual(resp.json()['error']['code'], code, body)
        self.assertEqual(self._post(url, {'relationship_id': self.relationship.id}).status_code, 200)

    def test_parent_update_every_field_reads_back(self):
        student = self._create_student('UM-P3')
        other = self._create_student('UM-P4')
        state = self.env.ref('base.state_in_mh')
        created = self._post('/api/v1/parents', {
            'name': 'Asha Parent', 'mobile': '9800099933', 'email': 'asha@um.test',
            'relationship_id': self.relationship.id, 'student_ids': [student.id], 'gender': 'f',
            'birth_date': '1985-05-06', 'address': {'city': 'Nagpur', 'state_id': state.id},
            'documents': {'additional': [PIXEL]},
            'account': {'username': 'asha.parent', 'password': 'AshaParent99'}})
        self.assertEqual(created.status_code, 201, created.text)
        data = created.json()['data']
        self.assertEqual((data['gender'], data['birth_date']), ('f', '1985-05-06'))
        self.assertEqual(data['address']['city'], 'Nagpur')
        self.assertEqual(data['address']['state']['id'], state.id)
        self.assertEqual(len(data['documents']['additional']), 1)
        document_id = data['documents']['additional'][0]['id']
        self.assertEqual(self.url_open(f"/api/v1/parents/{data['id']}/documents/{document_id}",
                                       headers=self._office()).status_code, 200)

        parent = self.env['op.parent'].browse(data['id'])
        url = f"/api/v1/parents/{data['id']}/update"
        resp = self._post(url, {
            'email': 'asha.new@um.test', 'mobile': '9800099944', 'street': '5 Top Level Rd',
            'student_ids': [student.id, other.id],
            'rte': {'category': 'sc', 'bpl_number': 'BPL-1', 'bpl_list_type': 'state',
                    'income_certificate_financial_year': '2025-26',
                    'category_certificate': {'data': PIXEL, 'filename': 'caste.png'}},
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertEqual((data['email'], data['mobile']), ('asha.new@um.test', '9800099944'))
        self.assertEqual((parent.name.email, parent.name.phone), ('asha.new@um.test', '9800099944'),
                         'The contact login credentials go to follows the parent.')
        self.assertEqual(data['address']['street'], '5 Top Level Rd')
        self.assertEqual(data['address']['city'], 'Nagpur')
        self.assertEqual(len(data['students']), 2)
        self.assertEqual(data['rte']['category'], 'sc')
        self.assertEqual(data['rte']['bpl_list_type'], 'state')
        self.assertEqual(data['rte']['category_certificate'], {'filename': 'caste.png'})
        self.assertIsNone(data['rte']['income_certificate'])

        removed = self._post(url, {'rte': {'category_certificate': None}}).json()['data']
        self.assertIsNone(removed['rte']['category_certificate'])

        for body, code in (
            ({'relationship_id': None}, 'missing_relationship_id'),
            ({'name': ' '}, 'missing_name'),
            ({'student_ids': []}, 'missing_student_ids'),
            ({'student_ids': [999999]}, 'invalid_student_ids'),
            ({'gender': 'x'}, 'invalid_gender'),
            ({'rte': {'category': 'rich'}}, 'invalid_category'),
            ({'rte': {'annual_income': -5}}, 'invalid_annual_income'),
            ({'address': {'state_id': 999999}}, 'invalid_state_id'),
        ):
            resp = self._post(url, body)
            self.assertEqual(resp.status_code, 400, body)
            self.assertEqual(resp.json()['error']['code'], code, body)
        # The RTE income cap is the model's check: a 400, nothing saved.
        capped = self._post(url, {'rte': {'category': 'weaker_section', 'annual_income': 900000}})
        self.assertEqual(capped.status_code, 400, capped.text)
        self.assertEqual(parent.rte_category, 'sc')
        # A student-only key used to 500 on parents.
        self.assertEqual(self._post(url, {'nationality': self.env.ref('base.in').id}).status_code, 200)
