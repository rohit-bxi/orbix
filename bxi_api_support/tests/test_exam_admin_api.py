# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportExamAdmin(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.exam_user = mail_new_test_user(
            cls.env, login='exa_staff', password='ExamPass1!',
            groups='base.group_user,openeducat_exam.group_op_exam_user')
        cls.teacher_user = mail_new_test_user(
            cls.env, login='exa_teacher', password='TeacherPass1!',
            groups='base.group_user,openeducat_core.group_op_faculty')
        cls.parent_user = mail_new_test_user(
            cls.env, login='exa_parent', password='ParentPass1!', groups='base.group_portal')
        cls.faculty = cls._create_faculty(cls.teacher_user, first_name='Exa')
        cls.course, cls.batch = cls._create_class('EXA')
        cls.maths = cls.env['op.subject'].create({'name': 'Exa Maths', 'code': 'EXAM'})
        cls.art = cls.env['op.subject'].create({'name': 'Exa Art', 'code': 'EXAA', 'subject_type': 'elective'})
        cls.other_subject = cls.env['op.subject'].create({'name': 'Exa Other', 'code': 'EXAO'})
        cls.course.subject_ids = cls.maths | cls.art
        cls.exam_type = cls.env['op.exam.type'].create({'name': 'Exa Term', 'code': 'EXAT'})
        cls.students = cls.env['op.student']
        for i, name in enumerate(('Zed', 'Amy', 'Moe')):
            student = cls._create_student(f'EXA-00{i}', first_name=name, last_name='Exa')
            enrolment = cls._enroll(student, cls.course, cls.batch)
            enrolment.roll_number = str(i + 1)
            cls.students |= student
        cls.parent = cls._create_parent(cls.parent_user, cls.students[0])
        classroom = cls.env['op.classroom'].create({'name': 'Exa Hall', 'code': 'EXA-H', 'capacity': 2})
        cls.room_a = cls.env['op.exam.room'].create({'name': 'Exa Room A', 'classroom_id': classroom.id,
                                                     'capacity': 2})
        cls.room_b = cls.env['op.exam.room'].create({'name': 'Exa Room B', 'classroom_id': classroom.id,
                                                     'capacity': 2})
        cls.grade_pass = cls.env['op.grade.configuration'].create({'min_per': 40, 'max_per': 100, 'result': 'Pass'})

    def _staff(self):
        return self._headers('exa_staff', 'ExamPass1!')

    def _post(self, path, payload=None, headers=None):
        return self.url_open(path, headers=headers or self._staff(), json=payload or {}, method='POST')

    def _session_payload(self, **extra):
        payload = {
            'name': 'Exa Mid Term', 'exam_code': 'EXA-MT', 'class_id': self.course.id, 'section_id': self.batch.id,
            'exam_type_id': self.exam_type.id, 'start_date': '2026-12-01', 'end_date': '2026-12-05',
            'exams': [{'subject_id': self.maths.id, 'start_time': '2026-12-01 04:00:00',
                       'end_time': '2026-12-01 06:00:00', 'total_marks': 100, 'passing_marks': 35}],
        }
        payload.update(extra)
        return payload

    def test_access(self):
        for headers in (self._headers('exa_teacher', 'TeacherPass1!'), self._headers('exa_parent', 'ParentPass1!')):
            self.assertEqual(self._post('/api/v1/exams/sessions', self._session_payload(), headers).status_code, 403)
            self.assertEqual(self.url_open('/api/v1/exams/marksheets', headers=headers).status_code, 403)
            self.assertEqual(self.url_open('/api/v1/exams/result-templates', headers=headers).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/exams/marksheets').status_code, 401)

    def test_create_session_with_exams(self):
        resp = self._post('/api/v1/exams/sessions', self._session_payload())
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertEqual(data['state'], 'draft')
        self.assertEqual(len(data['exams']), 1)
        exam = data['exams'][0]
        self.assertEqual(exam['exam_code'], 'EXA-MT-EXAM')
        self.assertEqual(exam['name'], 'Exa Maths - Exa Mid Term')
        self.assertEqual(exam['passing_marks'], 35)
        # A teacher of the class may read the session, a parent may not.
        self._enroll_teacher()
        detail = self.url_open(f"/api/v1/exams/sessions/{data['id']}", headers=self._headers('exa_teacher', 'TeacherPass1!'))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['data']['exams'][0]['attendee_count'], 0)
        self.assertEqual(self.url_open(f"/api/v1/exams/sessions/{data['id']}",
                                       headers=self._headers('exa_parent', 'ParentPass1!')).status_code, 403)

    def _enroll_teacher(self):
        self.faculty.write({'assigned_course_ids': [(4, self.course.id)], 'assigned_batch_ids': [(4, self.batch.id)]})

    def test_create_session_validation_is_all_or_nothing(self):
        bad_subject = self._session_payload(exams=[
            {'subject_id': self.maths.id, 'start_time': '2026-12-01 04:00:00', 'end_time': '2026-12-01 06:00:00',
             'total_marks': 100, 'passing_marks': 35},
            {'subject_id': self.other_subject.id, 'start_time': '2026-12-02 04:00:00',
             'end_time': '2026-12-02 06:00:00', 'total_marks': 100, 'passing_marks': 35},
        ])
        resp = self._post('/api/v1/exams/sessions', bad_subject)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'subject_not_in_class')
        self.assertFalse(self.env['op.exam.session'].search([('exam_code', '=', 'EXA-MT')]))
        # The model's own checks (a paper outside the session dates) roll back too.
        outside = self._session_payload(exams=[{
            'subject_id': self.maths.id, 'start_time': '2027-01-10 04:00:00', 'end_time': '2027-01-10 06:00:00',
            'total_marks': 100, 'passing_marks': 35}])
        self.assertEqual(self._post('/api/v1/exams/sessions', outside).status_code, 400)
        self.assertFalse(self.env['op.exam.session'].search([('exam_code', '=', 'EXA-MT')]))
        # Passing marks above total, wrong section, missing field, duplicate code.
        too_high = self._session_payload(exams=[dict(self._session_payload()['exams'][0], passing_marks=120)])
        self.assertEqual(self._post('/api/v1/exams/sessions', too_high).status_code, 400)
        _, other_batch = self._create_class('EXB')
        self.assertEqual(self._post('/api/v1/exams/sessions', self._session_payload(section_id=other_batch.id))
                         .json()['error']['code'], 'batch_course_mismatch')
        payload = self._session_payload()
        del payload['exam_type_id']
        self.assertEqual(self._post('/api/v1/exams/sessions', payload).json()['error']['code'], 'missing_exam_type_id')
        self.assertEqual(self._post('/api/v1/exams/sessions', self._session_payload()).status_code, 201)
        self.assertEqual(self._post('/api/v1/exams/sessions', self._session_payload()).json()['error']['code'],
                         'duplicate_exam_code')

    def test_update_and_add_exam(self):
        session = self._post('/api/v1/exams/sessions', self._session_payload(exams=[])).json()['data']
        add = self._post(f"/api/v1/exams/sessions/{session['id']}/exams", {
            'subject_id': self.art.id, 'start_time': '2026-12-02 04:00:00', 'end_time': '2026-12-02 05:00:00',
            'total_marks': 50, 'passing_marks': 20, 'exam_code': 'EXA-ART'})
        self.assertEqual(add.status_code, 201, add.text)
        exam_id = add.json()['data']['id']
        updated = self._post(f'/api/v1/exams/{exam_id}/update', {'total_marks': 60, 'name': 'Art paper'})
        self.assertEqual(updated.json()['data']['total_marks'], 60)
        self.assertEqual(updated.json()['data']['name'], 'Art paper')
        renamed = self._post(f"/api/v1/exams/sessions/{session['id']}/update", {'name': 'Exa Finals'})
        self.assertEqual(renamed.json()['data']['name'], 'Exa Finals')
        # Once scheduled, the session and its papers are frozen.
        self._post(f"/api/v1/exams/sessions/{session['id']}/schedule")
        self._post(f'/api/v1/exams/{exam_id}/schedule')
        self.assertEqual(self._post(f"/api/v1/exams/sessions/{session['id']}/update", {'name': 'X'})
                         .json()['error']['code'], 'invalid_state')
        self.assertEqual(self._post(f'/api/v1/exams/{exam_id}/update', {'name': 'X'}).json()['error']['code'],
                         'invalid_state')

    def test_assign_attendees(self):
        session = self._post('/api/v1/exams/sessions', self._session_payload()).json()['data']
        exam_id = session['exams'][0]['id']
        # Default: the whole section, in roll-number order, rooms filled in turn.
        resp = self._post(f'/api/v1/exams/{exam_id}/assign-attendees',
                          {'room_ids': [self.room_a.id, self.room_b.id]})
        self.assertEqual(resp.status_code, 200, resp.text)
        attendees = resp.json()['data']['attendees']
        self.assertEqual(len(attendees), 3)
        self.assertEqual([a['room']['id'] for a in attendees].count(self.room_a.id), 2)
        # Not enough seats.
        resp = self._post(f'/api/v1/exams/{exam_id}/assign-attendees', {'room_ids': [self.room_a.id]})
        self.assertEqual(resp.json()['error']['code'], 'not_enough_seats')
        # A hand-picked list replaces the earlier seating.
        resp = self._post(f'/api/v1/exams/{exam_id}/assign-attendees', {'student_ids': self.students[:1].ids})
        self.assertEqual(len(resp.json()['data']['attendees']), 1)
        # Electives: only students registered for the subject.
        art = self._post(f"/api/v1/exams/sessions/{session['id']}/exams", {
            'subject_id': self.art.id, 'start_time': '2026-12-02 04:00:00', 'end_time': '2026-12-02 05:00:00',
            'total_marks': 50, 'passing_marks': 20}).json()['data']
        self.assertEqual(self._post(f"/api/v1/exams/{art['id']}/assign-attendees").json()['error']['code'],
                         'no_students')
        self.env['op.subject.registration'].create({
            'student_id': self.students[1].id, 'course_id': self.course.id, 'batch_id': self.batch.id,
            'elective_subject_ids': [(6, 0, self.art.ids)], 'state': 'approved'})
        resp = self._post(f"/api/v1/exams/{art['id']}/assign-attendees")
        self.assertEqual([a['student']['id'] for a in resp.json()['data']['attendees']], self.students[1].ids)

    def test_room_busy_for_overlapping_exam(self):
        first = self._post('/api/v1/exams/sessions', self._session_payload()).json()['data']
        self._post(f"/api/v1/exams/{first['exams'][0]['id']}/assign-attendees",
                   {'room_ids': [self.room_a.id, self.room_b.id]})
        self._post(f"/api/v1/exams/{first['exams'][0]['id']}/schedule")
        # Another class's paper at the same time (openeducat refuses the
        # same subject twice at once, so a different one).
        course, batch = self._create_class('EXC')
        science = self.env['op.subject'].create({'name': 'Exc Science', 'code': 'EXCS'})
        course.subject_ids = science
        other = self._create_student('EXC-001')
        self._enroll(other, course, batch)
        payload = self._session_payload(exam_code='EXC-MT', class_id=course.id, section_id=batch.id)
        payload['exams'][0]['subject_id'] = science.id
        second = self._post('/api/v1/exams/sessions', payload).json()['data']
        resp = self._post(f"/api/v1/exams/{second['exams'][0]['id']}/assign-attendees", {'room_ids': [self.room_a.id]})
        self.assertEqual(resp.json()['error']['code'], 'room_busy')

    def test_result_template_and_marksheets(self):
        session = self._post('/api/v1/exams/sessions', self._session_payload()).json()['data']
        exam_id = session['exams'][0]['id']
        self._post(f'/api/v1/exams/{exam_id}/assign-attendees')
        template_payload = {'exam_session_id': session['id'], 'grade_ids': [self.grade_pass.id]}
        self.assertEqual(self._post('/api/v1/exams/result-templates', template_payload).json()['error']['code'],
                         'exams_not_done')
        for action in ('schedule', 'held'):
            self._post(f"/api/v1/exams/sessions/{session['id']}/{action}")
        for action in ('schedule', 'held'):
            self._post(f'/api/v1/exams/{exam_id}/{action}')
        self._post(f'/api/v1/exams/{exam_id}/marks', {'marks': [
            {'student_id': s.id, 'marks': 50 + i} for i, s in enumerate(self.students)]})
        self._post(f'/api/v1/exams/{exam_id}/result-updated')
        self._post(f'/api/v1/exams/{exam_id}/done')
        created = self._post('/api/v1/exams/result-templates', template_payload)
        self.assertEqual(created.status_code, 201, created.text)
        template = created.json()['data']
        self.assertEqual(template['grades'][0]['result'], 'Pass')
        listed = self.url_open(f"/api/v1/exams/result-templates?session_id={session['id']}", headers=self._staff())
        self.assertEqual([t['id'] for t in listed.json()['data']['templates']], [template['id']])
        generated = self._post(f"/api/v1/exams/result-templates/{template['id']}/generate")
        register_id = generated.json()['data']['marksheet_register_id']
        drafts = self.url_open('/api/v1/exams/marksheets?state=draft', headers=self._staff()).json()['data']
        self.assertIn(register_id, [m['id'] for m in drafts['marksheets']])
        detail = self.url_open(f'/api/v1/exams/marksheets/{register_id}', headers=self._staff()).json()['data']
        self.assertEqual(detail['students'], 3)
        self.assertEqual(len(detail['lines']), 3)
        self.assertEqual(self.url_open('/api/v1/exams/marksheets?state=nope', headers=self._staff()).status_code, 400)

    def test_masters(self):
        rooms = self.url_open('/api/v1/masters/exam-rooms', headers=self._staff()).json()['data']
        self.assertIn(self.room_a.id, [r['id'] for r in rooms['items']])
        grades = self.url_open('/api/v1/masters/grade-configurations', headers=self._staff()).json()['data']
        self.assertIn(self.grade_pass.id, [g['id'] for g in grades['items']])
        self.assertEqual(self.url_open('/api/v1/masters/exam-rooms',
                                       headers=self._headers('exa_parent', 'ParentPass1!')).status_code, 403)
