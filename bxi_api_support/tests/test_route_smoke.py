# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase

# GET routes without path parameters - must answer, never 500, for an admin.
LIST_ROUTES = [
    '/api/v1/masters', '/api/v1/me/children', '/api/v1/me/profile', '/api/v1/notifications',
    '/api/v1/notifications/unread-count', '/api/v1/assignments', '/api/v1/exams/sessions',
    '/api/v1/library/catalog', '/api/v1/library/reservations', '/api/v1/events', '/api/v1/me/event-registrations',
    '/api/v1/calendar/holidays', '/api/v1/leaves/to-approve', '/api/v1/admissions', '/api/v1/admissions/registers',
    '/api/v1/admissions/rte/my', '/api/v1/students', '/api/v1/teachers', '/api/v1/parents', '/api/v1/visitors',
    '/api/v1/visits', '/api/v1/visits/today', '/api/v1/dashboards', '/api/v1/dashboards/attendance',
    '/api/v1/subject-registrations', '/api/v1/academic/ptm-meetings/my', '/api/v1/transport/vehicles',
    '/api/v1/transport/drivers', '/api/v1/payments/orders', '/api/v1/auth/sessions',
    '/api/v1/announcements', '/api/v1/notices', '/api/v1/dashboards/fees', '/api/v1/dashboards/health',
]
# Routes taking a record id - an unknown id must give a clean 4xx.
MISSING_ID_ROUTES = [
    ('GET', '/api/v1/students/999999/profile'), ('GET', '/api/v1/students/999999/photo'),
    ('GET', '/api/v1/assignments/999999'), ('POST', '/api/v1/assignments/999999/publish'),
    ('GET', '/api/v1/assignments/999999/submissions'), ('POST', '/api/v1/assignments/submissions/999999/accept'),
    ('GET', '/api/v1/exams/999999/attendees'), ('POST', '/api/v1/exams/999999/held'),
    ('POST', '/api/v1/exams/sessions/999999/schedule'), ('POST', '/api/v1/exams/marksheets/999999/publish'),
    ('POST', '/api/v1/exams/result-templates/999999/generate'), ('GET', '/api/v1/exams/report-card/999999'),
    ('GET', '/api/v1/library/catalog/999999'), ('POST', '/api/v1/library/loans/999999/return'),
    ('POST', '/api/v1/library/reservations/999999/accept'), ('GET', '/api/v1/events/999999'),
    ('GET', '/api/v1/events/999999/registrations'), ('POST', '/api/v1/event-registrations/999999/cancel'),
    ('GET', '/api/v1/assessments/exams/999999/questions'), ('POST', '/api/v1/assessments/questions/999999/delete'),
    ('POST', '/api/v1/assessments/submissions/999999/re-evaluate'), ('POST', '/api/v1/leaves/999999/cancel'),
    ('POST', '/api/v1/leaves/999999/approve'), ('GET', '/api/v1/admissions/999999'),
    ('POST', '/api/v1/admissions/999999/confirm'), ('POST', '/api/v1/admissions/rte/999999/documents'),
    ('GET', '/api/v1/admissions/rte/999999/lottery-result'), ('POST', '/api/v1/students/999999/update'),
    ('GET', '/api/v1/teachers/999999'), ('POST', '/api/v1/teachers/999999/update'),
    ('POST', '/api/v1/parents/999999/update'), ('POST', '/api/v1/visits/999999/checkout'),
    ('POST', '/api/v1/subject-registrations/999999/approve'), ('GET', '/api/v1/certificates/999999/pdf'),
    ('GET', '/api/v1/fees/details/999999/receipt'), ('POST', '/api/v1/fees/structures/999999/duplicate'),
    ('POST', '/api/v1/uniform/stock/999999/receive'), ('POST', '/api/v1/transport/stops/999999/update'),
    ('GET', '/api/v1/canteen/wallets/999999/transactions'), ('POST', '/api/v1/notifications/999999/read'),
    ('GET', '/api/v1/attendance/students/999999/summary'), ('POST', '/api/v1/attendance/sessions/999999/bulk-mark'),
    ('GET', '/api/v1/teacher/classes/999999/students'),
]


@tagged('post_install', '-at_install')
class TestBxiApiSupportRouteSmoke(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin_user = mail_new_test_user(
            cls.env, login='smoke_admin',
            groups='base.group_user,base.group_system,openeducat_core.group_op_back_office_admin,'
                   'openeducat_core.group_op_faculty',
            password='SmokePass1!')
        cls._create_faculty(cls.admin_user, first_name='Smoke')
        cls.admin_user.employee_id or cls.env['hr.employee'].create({'name': 'Smoke', 'user_id': cls.admin_user.id})

    def test_list_routes_never_crash(self):
        headers = self._headers('smoke_admin', 'SmokePass1!')
        for path in LIST_ROUTES:
            resp = self.url_open(path, headers=headers)
            self.assertLess(resp.status_code, 500, f'{path}: {resp.text[:300]}')
            self.assertIn(resp.status_code, (200, 400, 403, 404), path)

    def test_unknown_ids_get_clean_4xx(self):
        headers = self._headers('smoke_admin', 'SmokePass1!')
        for method, path in MISSING_ID_ROUTES:
            resp = self.url_open(path, headers=headers, method=method, json={'x': 1} if method == 'POST' else None)
            self.assertIn(resp.status_code, (400, 403, 404, 501), f'{method} {path}: {resp.status_code} {resp.text[:300]}')


@tagged('post_install', '-at_install')
class TestBxiApiSupportRemainingRoutes(ApiSupportHttpCase):
    """Happy paths for routes not covered by the area test files."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course, cls.batch = cls._create_class('RMN')
        cls.office_user = mail_new_test_user(
            cls.env, login='rmn_office',
            groups='base.group_user,openeducat_core.group_op_back_office_admin,'
                   'openeducat_admission.group_op_admission_user,'
                   'bxi_school_event_management.group_school_event_coordinator',
            password='OfficePass1!')
        cls.teacher_user = mail_new_test_user(
            cls.env, login='rmn_teacher', groups='base.group_user,openeducat_core.group_op_faculty',
            password='TeacherPass1!')
        cls.parent_user = mail_new_test_user(
            cls.env, login='rmn_parent', groups='base.group_portal', password='ParentPass1!')
        cls.student = cls._create_student('RMN-001', first_name='Rem', last_name='Kid')
        cls._enroll(cls.student, cls.course, cls.batch)
        cls.parent = cls._create_parent(cls.parent_user, cls.student)
        cls.faculty = cls._create_faculty(cls.teacher_user, first_name='Rmn')
        cls.faculty.emp_id = cls.env['hr.employee'].create({'name': 'Rmn Teacher', 'user_id': cls.teacher_user.id})

    def test_teacher_timetable_window(self):
        subject = self.env['op.subject'].create({'name': 'Rmn Art', 'code': 'RMNART'})
        start = fields.Datetime.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
        session = self.env['op.session'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id, 'subject_id': subject.id,
            'faculty_id': self.faculty.id, 'start_datetime': start, 'end_datetime': start + timedelta(hours=1)})
        data = self.url_open('/api/v1/teacher/timetable', headers=self._headers('rmn_teacher', 'TeacherPass1!')).json()
        self.assertIn(session.id, [p['id'] for p in data['data']['periods']])
        bad = self.url_open('/api/v1/teacher/timetable?date_from=xx', headers=self._headers('rmn_teacher', 'TeacherPass1!'))
        self.assertEqual(bad.json()['error']['code'], 'invalid_date')

    def test_leave_cancel(self):
        leave_type = self.env['hr.leave.type'].create({
            'name': 'Rmn Leave', 'requires_allocation': False, 'request_unit': 'day', 'company_id': self.env.company.id})
        monday = fields.Date.today() + timedelta(days=(7 - fields.Date.today().weekday()) + 7)
        headers = self._headers('rmn_teacher', 'TeacherPass1!')
        leave_id = self.url_open('/api/v1/leaves', headers=headers, json={
            'type_id': leave_type.id, 'date_from': fields.Date.to_string(monday),
            'date_to': fields.Date.to_string(monday)}).json()['data']['id']
        cancelled = self.url_open(f'/api/v1/leaves/{leave_id}/cancel', headers=headers, json={'reason': 'No longer needed'})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()['data']['state'], 'cancel')
        other = self.url_open(f'/api/v1/leaves/{leave_id}/cancel', headers=self._headers('rmn_office', 'OfficePass1!'),
                              json={'reason': 'x'})
        self.assertIn(other.status_code, (403, 404))

    def test_people_reads_and_updates(self):
        office = self._headers('rmn_office', 'OfficePass1!')
        parents = self.url_open(f'/api/v1/parents?student_id={self.student.id}', headers=office).json()['data']['parents']
        self.assertEqual([p['id'] for p in parents], self.parent.ids)
        updated = self.url_open(f'/api/v1/parents/{self.parent.id}/update', headers=office, json={'mobile': '9811199999'})
        self.assertEqual(updated.json()['data']['mobile'], '9811199999')
        teacher = self.url_open(f'/api/v1/teachers/{self.faculty.id}', headers=office).json()['data']
        self.assertEqual(teacher['id'], self.faculty.id)
        renamed = self.url_open(f'/api/v1/teachers/{self.faculty.id}/update', headers=office, json={'phone': '9822200000'})
        self.assertEqual(renamed.json()['data']['phone'], '9822200000')
        self.assertEqual(self.url_open('/api/v1/teachers', headers=self._headers('rmn_parent', 'ParentPass1!')).status_code, 403)
        teacher_view = self.url_open('/api/v1/students', headers=self._headers('rmn_teacher', 'TeacherPass1!'))
        self.assertEqual(teacher_view.json()['meta']['total'], 0, 'Teaches no section yet.')

    def test_admissions_office_reads(self):
        today = fields.Date.today()
        register = self.env['op.admission.register'].create({
            'name': 'Rmn Intake', 'course_id': self.course.id, 'start_date': today - timedelta(days=1),
            'end_date': today + timedelta(days=10), 'min_count': 1, 'max_count': 5, 'state': 'application'})
        admission = self.env['op.admission'].create({
            'name': 'Rmn Applicant', 'first_name': 'Rmn', 'last_name': 'Applicant', 'gender': 'm',
            'birth_date': '2018-01-01', 'course_id': self.course.id, 'register_id': register.id,
            'application_date': fields.Datetime.now(), 'email': 'rmn@example.com'})
        office = self._headers('rmn_office', 'OfficePass1!')
        listing = self.url_open(f'/api/v1/admissions?register_id={register.id}', headers=office).json()
        self.assertEqual([a['id'] for a in listing['data']['admissions']], admission.ids)
        detail = self.url_open(f'/api/v1/admissions/{admission.id}', headers=office).json()['data']
        self.assertEqual(detail['email'], 'rmn@example.com')

    def test_event_coordinator_registrations_and_payment_orders(self):
        start = fields.Datetime.now() + timedelta(days=2)
        event = self.env['event.event'].create({
            'name': 'Rmn Fair', 'date_begin': start, 'date_end': start + timedelta(hours=3), 'target_audience': 'everyone'})
        self.url_open(f'/api/v1/events/{event.id}/register', headers=self._headers('rmn_parent', 'ParentPass1!'),
                      json={'student_id': self.student.id})
        regs = self.url_open(f'/api/v1/events/{event.id}/registrations', headers=self._headers('rmn_office', 'OfficePass1!'))
        self.assertEqual(len(regs.json()['data']['registrations']), 1)
        self.assertEqual(self.url_open(f'/api/v1/events/{event.id}/registrations',
                                       headers=self._headers('rmn_parent', 'ParentPass1!')).status_code, 403)
        orders = self.url_open(f'/api/v1/payments/orders?student_id={self.student.id}',
                               headers=self._headers('rmn_parent', 'ParentPass1!'))
        self.assertEqual(orders.status_code, 200)
        self.assertEqual(orders.json()['data']['orders'], [])
