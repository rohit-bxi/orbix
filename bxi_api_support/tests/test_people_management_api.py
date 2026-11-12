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
                'enrollment': {'course_id': self.course.id, 'batch_id': self.batch.id, 'roll_number': '7'}}
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
            enrollment={'course_id': self.course.id, 'batch_id': self.batch.id, 'roll_number': '8'}))
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
        self.assertEqual(self._post(url, {'status': 'expelled'}).json()['error']['code'], 'invalid_status')

    # -- parents ------------------------------------------------------------------------

    def test_parent_profile_status_and_derived_classes(self):
        student = self._create_student('UM-P1')
        self._enroll(student, self.course, self.batch)
        resp = self._post('/api/v1/parents', {
            'name': 'Pia Parent', 'mobile': '9800099911', 'relationship_id': self.relationship.id,
            'student_ids': [student.id], 'image': PIXEL})
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
            'student_ids': [student.id], 'create_login': True})
        self.assertEqual(resp.status_code, 400, 'A login needs an email.')
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
