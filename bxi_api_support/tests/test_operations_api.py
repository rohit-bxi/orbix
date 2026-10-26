# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportOperations(ApiSupportHttpCase):
    """Admin/ops surface: admissions, RTE family side, people, visitors,
    dashboards, fee structures, stock, bulk refunds, transport set-up and
    elective registration."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course, cls.batch = cls._create_class('OPS')
        cls.office_user = mail_new_test_user(
            cls.env, login='ops_office',
            groups='base.group_user,openeducat_core.group_op_back_office_admin,'
                   'openeducat_admission.group_op_admission_user,'
                   'bxi_academic_management.group_academic_coordinator',
            password='OfficePass1!')
        cls.gate_user = mail_new_test_user(
            cls.env, login='ops_gate', groups='base.group_user,visitor_management.group_visitor_officer',
            password='GatePass1!')
        cls.parent_user = mail_new_test_user(
            cls.env, login='ops_parent', groups='base.group_portal', password='ParentPass1!')
        cls.student = cls._create_student('OPS-001', first_name='Ops', last_name='Kid')
        cls._enroll(cls.student, cls.course, cls.batch)
        cls._create_parent(cls.parent_user, cls.student)

    def _office(self):
        return self._headers('ops_office', 'OfficePass1!')

    def _parent(self):
        return self._headers('ops_parent', 'ParentPass1!')

    # -- admissions ----------------------------------------------------------------

    def test_public_apply_status_and_office_workflow(self):
        today = fields.Date.today()
        register = self.env['op.admission.register'].create({
            'name': 'Ops Intake', 'course_id': self.course.id, 'start_date': today - timedelta(days=1),
            'end_date': today + timedelta(days=30), 'min_count': 1, 'max_count': 10, 'state': 'application',
            'minimum_age_criteria': 3,
        })
        registers = self.url_open('/api/v1/admissions/registers').json()['data']['registers']
        self.assertIn(register.id, [r['id'] for r in registers])

        bad = self.url_open('/api/v1/admissions/apply', json={'register_id': register.id, 'first_name': 'A'})
        self.assertEqual(bad.status_code, 400)
        apply = self.url_open('/api/v1/admissions/apply', json={
            'register_id': register.id, 'first_name': 'Nia', 'last_name': 'Applicant', 'gender': 'f',
            'birth_date': '2018-05-01', 'email': 'nia@example.com', 'mobile': '9800011122',
        })
        self.assertEqual(apply.status_code, 201, apply.text)
        number = apply.json()['data']['application_number']
        self.assertEqual(apply.json()['data']['state'], 'submit')

        wrong_dob = self.url_open('/api/v1/admissions/status', json={
            'application_number': number, 'birth_date': '2018-05-02'})
        self.assertEqual(wrong_dob.status_code, 404)
        status = self.url_open('/api/v1/admissions/status', json={
            'application_number': number, 'birth_date': '2018-05-01'})
        self.assertEqual(status.json()['data']['state'], 'submit')

        admission_id = apply.json()['data']['id']
        self.assertEqual(self.url_open(f'/api/v1/admissions/{admission_id}', headers=self._parent()).status_code, 403)
        skip = self.url_open(f'/api/v1/admissions/{admission_id}/enroll', headers=self._office(), method='POST')
        self.assertEqual(skip.json()['error']['code'], 'invalid_transition')
        for action, state in (('confirm', 'confirm'), ('admit', 'admission'), ('enroll', 'done')):
            resp = self.url_open(f'/api/v1/admissions/{admission_id}/{action}', headers=self._office(), method='POST')
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertEqual(resp.json()['data']['state'], state)
        self.assertTrue(resp.json()['data']['student_id'])

    def test_rte_apply_documents_and_lottery_result(self):
        rte_course = self.env['op.course'].create({'name': 'Ops RTE', 'code': 'OPS-RTE', 'rte_active': True,
                                                   'rte_seats_manual': 5})
        self.env['op.admission.register'].create({'name': 'Ops RTE Register', 'min_count': 1, 'max_count': 30})
        payload = {'first_name': 'Ravi', 'last_name': 'Rte', 'birth_date': '2019-03-01', 'email': 'ravi@example.com',
                   'mobile': '9800022233', 'rte_aadhaar_number': '999988887777', 'course_ids': [rte_course.id]}
        missing = self.url_open('/api/v1/admissions/rte/apply', headers=self._parent(),
                                json=dict(payload, course_ids=[]))
        self.assertEqual(missing.json()['error']['fields']['course_ids'], 'missing')
        not_rte = self.url_open('/api/v1/admissions/rte/apply', headers=self._parent(),
                                json=dict(payload, course_ids=[self.course.id]))
        self.assertEqual(not_rte.json()['error']['fields']['course_ids'], 'not_rte_active')
        applied = self.url_open('/api/v1/admissions/rte/apply', headers=self._parent(), json=payload)
        self.assertEqual(applied.status_code, 201, applied.text)
        admission_id = applied.json()['data']['id']

        mine = self.url_open('/api/v1/admissions/rte/my', headers=self._parent()).json()['data']['applications']
        self.assertEqual([a['id'] for a in mine], [admission_id])
        upload = self.url_open(f'/api/v1/admissions/rte/{admission_id}/documents', headers=self._parent(), json={
            'doc_type': 'birth_cert',
            'attachments': [{'name': 'birth.pdf', 'data': base64.b64encode(b'%PDF-1.4').decode()}]})
        self.assertEqual(upload.status_code, 201, upload.text)
        again = self.url_open(f'/api/v1/admissions/rte/{admission_id}/documents', headers=self._parent(), json={
            'doc_type': 'birth_cert',
            'attachments': [{'name': 'birth2.pdf', 'data': base64.b64encode(b'%PDF-1.5').decode()}]})
        self.assertEqual(again.json()['data']['id'], upload.json()['data']['id'], 'Re-upload replaces.')
        other = self.url_open(f'/api/v1/admissions/rte/{admission_id}/documents',
                              headers=self._office(), json={'doc_type': 'photo'})
        self.assertEqual(other.status_code, 404)
        result = self.url_open(f'/api/v1/admissions/rte/{admission_id}/lottery-result', headers=self._parent())
        self.assertEqual(result.json()['data']['results'], [])

    # -- people ----------------------------------------------------------------------

    def test_people_directory(self):
        family = self.url_open('/api/v1/students', headers=self._parent())
        self.assertEqual(family.status_code, 403)
        created = self.url_open('/api/v1/students', headers=self._office(), json={
            'first_name': 'New', 'last_name': 'Joiner', 'gender': 'm', 'gr_no': 'OPS-NEW',
            'enrollment': {'course_id': self.course.id, 'batch_id': self.batch.id, 'roll_number': '42'}})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()['data']['roll_number'], '42')
        listing = self.url_open(f'/api/v1/students?batch_id={self.batch.id}', headers=self._office()).json()
        self.assertEqual(listing['meta']['total'], 2)
        updated = self.url_open(f"/api/v1/students/{created.json()['data']['id']}/update", headers=self._office(),
                                json={'blood_group': 'O+'})
        self.assertEqual(updated.status_code, 200)

        teacher = self.url_open('/api/v1/teachers', headers=self._office(), json={
            'first_name': 'Tara', 'last_name': 'Teach', 'gender': 'female', 'birth_date': '1990-01-01'})
        self.assertEqual(teacher.status_code, 201, teacher.text)
        relationship = self.env['op.parent.relationship'].search([], limit=1)
        parent = self.url_open('/api/v1/parents', headers=self._office(), json={
            'name': 'Pat Parent', 'mobile': '9800033344', 'relationship_id': relationship.id,
            'student_ids': [created.json()['data']['id']]})
        self.assertEqual(parent.status_code, 201, parent.text)
        bad_ids = self.url_open('/api/v1/parents', headers=self._office(), json={
            'name': 'Bad', 'mobile': '1', 'relationship_id': relationship.id, 'student_ids': ['abc']})
        self.assertEqual(bad_ids.status_code, 400)

    # -- visitors ----------------------------------------------------------------------

    def test_visitor_gate_flow(self):
        self.assertEqual(self.url_open('/api/v1/visits/today', headers=self._parent()).status_code, 403)
        gate = self._headers('ops_gate', 'GatePass1!')
        visitor = self.url_open('/api/v1/visitors', headers=gate, json={
            'name': 'Vic Visitor', 'company': 'Supplies Co', 'phone': '9800044455', 'type': 'supplier'})
        self.assertEqual(visitor.status_code, 201, visitor.text)
        host = self.env['hr.employee'].create({'name': 'Ops Host'})
        visit = self.url_open('/api/v1/visits', headers=gate, json={
            'visitor_id': visitor.json()['data']['id'], 'host_employee_id': host.id, 'purpose': 'Delivery'})
        self.assertEqual(visit.status_code, 201, visit.text)
        self.assertEqual(visit.json()['data']['state'], 'checkin')
        twice = self.url_open('/api/v1/visits', headers=gate, json={
            'visitor_id': visitor.json()['data']['id'], 'host_employee_id': host.id})
        self.assertEqual(twice.json()['error']['code'], 'already_checked_in')
        today = self.url_open('/api/v1/visits/today', headers=gate).json()['data']
        self.assertEqual(today['on_campus_count'], 1)
        out = self.url_open(f"/api/v1/visits/{visit.json()['data']['id']}/checkout", headers=gate, method='POST')
        self.assertEqual(out.json()['data']['state'], 'checkout')

    # -- dashboards ----------------------------------------------------------------

    def test_dashboards_are_permission_scoped(self):
        gate = self._headers('ops_gate', 'GatePass1!')
        self.assertEqual(self.url_open('/api/v1/dashboards', headers=gate).json()['data']['dashboards'], ['visitor'])
        self.assertEqual(self.url_open('/api/v1/dashboards', headers=self._parent()).json()['data']['dashboards'], [])
        self.assertEqual(self.url_open('/api/v1/dashboards/canteen', headers=gate).status_code, 403)
        visitor = self.url_open('/api/v1/dashboards/visitor', headers=gate)
        self.assertEqual(visitor.status_code, 200, visitor.text)
        attendance = self.url_open('/api/v1/dashboards/attendance', headers=self._office())
        self.assertEqual(attendance.status_code, 200)
        self.assertIn('periods', attendance.json()['data'])
        self.assertEqual(self.url_open('/api/v1/dashboards/rte', headers=self._parent()).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/dashboards/nope', headers=self._office()).status_code, 404)

    # -- elective registration --------------------------------------------------------

    def test_elective_registration(self):
        elective = self.env['op.subject'].create({'name': 'Ops Music', 'code': 'OPSMUS', 'subject_type': 'elective'})
        core = self.env['op.subject'].create({'name': 'Ops Maths', 'code': 'OPSMATH', 'subject_type': 'compulsory'})
        self.course.subject_ids = [(6, 0, [elective.id, core.id])]
        bad = self.url_open('/api/v1/subject-registrations', headers=self._parent(), json={
            'student_id': self.student.id, 'elective_subject_ids': [core.id]})
        self.assertEqual(bad.json()['error']['code'], 'invalid_elective')
        created = self.url_open('/api/v1/subject-registrations', headers=self._parent(), json={
            'student_id': self.student.id, 'elective_subject_ids': [elective.id]})
        self.assertEqual(created.status_code, 201, created.text)
        reg = created.json()['data']
        self.assertEqual([s['id'] for s in reg['compulsory_subjects']], core.ids)
        self.url_open(f"/api/v1/subject-registrations/{reg['id']}/submit", headers=self._parent(), method='POST')
        self.assertEqual(self.url_open(f"/api/v1/subject-registrations/{reg['id']}/approve", headers=self._parent(),
                                       method='POST').status_code, 403)
        approved = self.url_open(f"/api/v1/subject-registrations/{reg['id']}/approve", headers=self._office(),
                                 method='POST')
        self.assertEqual(approved.json()['data']['state'], 'approved')
        enrollment = self.student.course_detail_ids.filtered(lambda l: l.course_id == self.course)
        self.assertEqual(set(enrollment.subject_ids.ids), {elective.id, core.id})


@tagged('post_install', '-at_install')
class TestBxiApiSupportOperationsStaffDesks(ApiSupportHttpCase):
    """Fee office, uniform store, refund desk and transport office."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fee_user = mail_new_test_user(
            cls.env, login='ops_fee', groups='base.group_user,openeducat_fees.group_openeducat_fees_user',
            password='FeePass1!')
        cls.uniform_user = mail_new_test_user(
            cls.env, login='ops_uniform', groups='base.group_user,bxi_uniform_management.group_uniform_staff',
            password='UniformPass1!')
        cls.refund_user = mail_new_test_user(
            cls.env, login='ops_refund', groups='base.group_user,bxi_student_refund_management.group_refund_staff',
            password='RefundPass1!')
        cls.transport_user = mail_new_test_user(
            cls.env, login='ops_transport',
            groups='base.group_user,bxi_school_transport_bus_management.group_transport_staff',
            password='TransportPass1!')

    def test_fee_structure_authoring(self):
        product = self.env['product.product'].create({
            'name': 'Ops Tuition', 'lst_price': 1000.0, 'property_account_income_id': self.income_account.id})
        category = self.env['bxi.fee.category'].create({'name': 'Ops Tuition', 'code': 'OPS-TUI', 'product_id': product.id})
        headers = self._headers('ops_fee', 'FeePass1!')
        created = self.url_open('/api/v1/fees/structures', headers=headers, json={
            'name': 'Ops Structure', 'code': 'OPS-FS1', 'fees_terms': 'fixed_date', 'installment_type': 'one_time',
            'first_due_date': fields.Date.to_string(fields.Date.today() + timedelta(days=30)),
            'category_lines': [{'category_id': category.id, 'amount': 1200.0}]})
        self.assertEqual(created.status_code, 201, created.text)
        structure_id = created.json()['data']['id']
        self.assertEqual(created.json()['data']['total_amount'], 1200.0)
        updated = self.url_open(f'/api/v1/fees/structures/{structure_id}/update', headers=headers, json={
            'category_lines': [{'category_id': category.id, 'amount': 1500.0}]})
        self.assertEqual(updated.json()['data']['total_amount'], 1500.0)
        generated = self.url_open(f'/api/v1/fees/structures/{structure_id}/generate-installments', headers=headers,
                                  method='POST')
        self.assertEqual(generated.status_code, 200, generated.text)
        copy = self.url_open(f'/api/v1/fees/structures/{structure_id}/duplicate', headers=headers, method='POST')
        self.assertEqual(copy.status_code, 201, copy.text)
        self.assertEqual(copy.json()['data']['state'], 'draft')
        self.assertNotEqual(copy.json()['data']['id'], structure_id)

    def test_uniform_stock_receipt(self):
        shirt = self.env['product.product'].create({'name': 'Ops Shirt', 'is_uniform_item': True})
        stock = self.env['bxi.uniform.stock'].create({'product_id': shirt.id})
        resp = self.url_open(f'/api/v1/uniform/stock/{stock.id}/receive', headers=self._headers('ops_uniform', 'UniformPass1!'),
                             json={'quantity': 25, 'note': 'Vendor delivery'})
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(resp.json()['data']['quantity_on_hand'], 25.0)
        bad = self.url_open(f'/api/v1/uniform/stock/{stock.id}/receive', headers=self._headers('ops_uniform', 'UniformPass1!'),
                            json={'quantity': -3})
        self.assertEqual(bad.status_code, 400)

    def test_bulk_refunds(self):
        student = self._create_student('OPS-RF1')
        self._create_posted_invoice(student, 1000.0, 1300.0)
        resp = self.url_open('/api/v1/refunds/bulk', headers=self._headers('ops_refund', 'RefundPass1!'), json={
            'student_ids': [student.id], 'refund_type': 'fee_overpayment', 'reason': 'Overpaid'})
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(resp.json()['data']['refunds'][0]['refund_amount'], 300.0)

    def test_transport_setup(self):
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Ops Brand'})
        vehicle = self.env['fleet.vehicle'].create({
            'model_id': self.env['fleet.vehicle.model'].create({'name': 'Ops Bus', 'brand_id': brand.id}).id,
            'is_school_bus': True, 'seats': 40})
        fee = self.env['product.product'].create({'name': 'Ops Bus Fee', 'type': 'service',
                                                  'property_account_income_id': self.income_account.id})
        route = self.env['bxi.transport.route'].create({
            'name': 'Ops Route', 'vehicle_id': vehicle.id, 'fee_product_id': fee.id, 'fee_amount': 100.0})
        headers = self._headers('ops_transport', 'TransportPass1!')
        added = self.url_open(f'/api/v1/transport/routes/{route.id}/stops', headers=headers,
                              json={'name': 'Ops Stop', 'pickup_time': 7.25})
        self.assertEqual(added.status_code, 201, added.text)
        stop_id = added.json()['data']['stops'][0]['id']
        moved = self.url_open(f'/api/v1/transport/stops/{stop_id}/update', headers=headers, json={'pickup_time': 7.5})
        self.assertEqual(moved.status_code, 200)
        vehicles = self.url_open('/api/v1/transport/vehicles', headers=headers).json()['data']['vehicles']
        self.assertIn(vehicle.id, [v['id'] for v in vehicles])
        self.assertEqual(self.url_open('/api/v1/transport/drivers', headers=headers).status_code, 200)
        removed = self.url_open(f'/api/v1/transport/stops/{stop_id}/delete', headers=headers, method='POST')
        self.assertEqual(removed.json()['data']['stops'], [])
