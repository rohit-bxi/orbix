# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportLabRecords(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.instructor_user = mail_new_test_user(
            cls.env, login='lrec_instructor', password='InstructorPass1!',
            groups='base.group_user,op_student_lab_management.group_lab_instructor')
        cls.other_user = mail_new_test_user(
            cls.env, login='lrec_other', password='OtherPass1!',
            groups='base.group_user,op_student_lab_management.group_lab_instructor')
        cls.parent_user = mail_new_test_user(
            cls.env, login='lrec_parent', password='ParentPass1!', groups='base.group_portal')
        cls.faculty = cls._create_faculty(cls.instructor_user, first_name='Lrec')
        cls.course, cls.batch = cls._create_class('LREC')
        cls.students = cls.env['op.student']
        for i in range(2):
            student = cls._create_student(f'LREC-00{i}', first_name=f'Lab{i}')
            cls._enroll(student, cls.course, cls.batch)
            cls.students |= student
        cls.outsider = cls._create_student('LREC-099')
        cls.parent = cls._create_parent(cls.parent_user, cls.students[0])
        room = cls.env['lab.room'].create({'name': 'Lrec Room', 'code': 'LREC-R'})
        cls.experiment = cls.env['lab.experiment'].create({'name': 'Titration', 'code': 'LREC-E1', 'max_marks': 20})
        cls.session = cls.env['lab.session'].create({
            'room_id': room.id, 'course_id': cls.course.id, 'batch_id': cls.batch.id,
            'faculty_id': cls.faculty.id, 'experiment_id': cls.experiment.id,
            'start_time': 9.0, 'end_time': 10.0, 'student_ids': [(6, 0, cls.students.ids)],
        })

    def _instructor(self):
        return self._headers('lrec_instructor', 'InstructorPass1!')

    def _post(self, path, payload, headers=None):
        return self.url_open(path, headers=headers or self._instructor(), json=payload, method='POST')

    def test_access(self):
        other = self._headers('lrec_other', 'OtherPass1!')
        path = f'/api/v1/lab/sessions/{self.session.id}/attendance'
        self.assertEqual(self.url_open(path, headers=other).status_code, 403)
        self.assertEqual(self._post(path, {'records': []}, other).status_code, 403)
        self.assertEqual(self.url_open(path).status_code, 401)

    def test_attendance(self):
        path = f'/api/v1/lab/sessions/{self.session.id}/attendance'
        payload = {'records': [{'student_id': self.students[0].id, 'status': 'late'}]}
        self.assertEqual(self._post(path, payload).json()['error']['code'], 'invalid_state')
        self.session.action_confirm()  # creates a "present" line per student
        resp = self._post(path, {'records': [
            {'student_id': self.students[0].id, 'status': 'late', 'remark': 'Bus'},
            {'student_id': self.students[1].id, 'status': 'absent'},
        ]})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()['data']
        self.assertEqual(data['summary'], {'present': 0, 'absent': 1, 'late': 1, 'unmarked': 0})
        self.assertEqual(len(self.session.attendance_ids), 2)
        self.assertEqual(self._post(path, {'records': [{'student_id': self.outsider.id}]}).json()['error']['code'],
                         'not_in_session')
        self.assertEqual(self._post(path, {'records': [{'student_id': self.students[0].id, 'status': 'x'}]})
                         .json()['error']['code'], 'invalid_status')

    def test_results_and_family_view(self):
        path = f'/api/v1/lab/sessions/{self.session.id}/results'
        rows = {'results': [{'student_id': self.students[0].id, 'marks_obtained': 18}]}
        self.assertEqual(self._post(path, rows).json()['error']['code'], 'invalid_state')
        self.session.action_confirm()
        self.session.action_start()
        resp = self._post(path, rows)
        self.assertEqual(resp.status_code, 200, resp.text)
        result = resp.json()['data']['results'][0]
        self.assertEqual(result['grade'], 'A+')
        # Entering again updates the same row.
        resp = self._post(path, {'results': [{'student_id': self.students[0].id, 'marks_obtained': 9,
                                              'remark': 'Redo'}]})
        self.assertEqual(len(resp.json()['data']['results']), 1)
        self.assertEqual(resp.json()['data']['results'][0]['grade'], 'D')
        self.assertEqual(self._post(path, {'results': [{'student_id': self.students[1].id, 'marks_obtained': 25}]})
                         .json()['error']['code'], 'invalid_marks')
        family = self.url_open(f'/api/v1/lab/results?student_id={self.students[0].id}',
                               headers=self._headers('lrec_parent', 'ParentPass1!'))
        self.assertEqual(family.status_code, 200)
        self.assertEqual(family.json()['data']['results'][0]['marks_obtained'], 9)
        self.assertEqual(family.json()['data']['attendance']['present'], 1)
        self.assertEqual(self.url_open(f'/api/v1/lab/results?student_id={self.students[1].id}',
                                       headers=self._headers('lrec_parent', 'ParentPass1!')).status_code, 403)

    def test_session_without_experiment_needs_one(self):
        self.session.write({'experiment_id': False})
        self.session.action_confirm()
        self.session.action_start()
        path = f'/api/v1/lab/sessions/{self.session.id}/results'
        rows = {'results': [{'student_id': self.students[0].id, 'marks_obtained': 5}]}
        self.assertEqual(self._post(path, rows).json()['error']['code'], 'missing_experiment_id')
        self.assertEqual(self._post(path, dict(rows, experiment_id=self.experiment.id)).status_code, 200)

    def test_read_attendance_and_results(self):
        path = f'/api/v1/lab/sessions/{self.session.id}'
        before = self.url_open(f'{path}/attendance', headers=self._instructor()).json()['data']
        self.assertEqual(before['summary']['unmarked'], 2)
        self.session.action_confirm()
        self._post(f'{path}/attendance', {'records': [{'student_id': self.students[0].id, 'status': 'late'}]})
        attendance = self.url_open(f'{path}/attendance', headers=self._instructor())
        self.assertEqual(attendance.status_code, 200, attendance.text)
        statuses = {row['student']['id']: row['status'] for row in attendance.json()['data']['students']}
        self.assertEqual(statuses, {self.students[0].id: 'late', self.students[1].id: 'present'})

        self.session.action_start()
        self._post(f'{path}/results', {'results': [{'student_id': self.students[1].id, 'marks_obtained': 15}]})
        results = self.url_open(f'{path}/results', headers=self._instructor())
        self.assertEqual(results.status_code, 200, results.text)
        self.assertEqual([(r['student']['id'], r['marks_obtained']) for r in results.json()['data']['results']],
                         [(self.students[1].id, 15)])
        filtered = self.url_open(f'{path}/results?experiment_id={self.experiment.id}', headers=self._instructor())
        self.assertEqual(len(filtered.json()['data']['results']), 1)
        self.assertEqual(self.url_open(f'{path}/results', headers=self._headers('lrec_other', 'OtherPass1!')).status_code, 403)
