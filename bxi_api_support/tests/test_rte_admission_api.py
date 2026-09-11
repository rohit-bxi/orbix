# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportRteAdmission(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coordinator_user = mail_new_test_user(
            cls.env, login='rte_api_coordinator',
            groups='base.group_user,bxi_rte_admission.group_rte_school_coordinator',
            password='CoordPass1!')
        cls.district_user = mail_new_test_user(
            cls.env, login='rte_api_district',
            groups='base.group_user,bxi_rte_admission.group_rte_district_officer',
            password='DistrictPass1!')
        cls.parent_user = mail_new_test_user(
            cls.env, login='rte_api_parent', groups='base.group_user', password='ParentPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='rte_api_other', groups='base.group_user', password='OtherPass1!')

        cls.academic_year = cls.env['op.academic.year'].create({
            'name': 'RTE API AY', 'start_date': '2026-06-01', 'end_date': '2027-03-31',
        })
        cls.course = cls.env['op.course'].create({
            'name': 'RTE API Course', 'code': 'RTE-C1', 'rte_active': True, 'rte_seats_manual': 5,
        })
        cls.register = cls.env['op.admission.register'].create({
            'name': 'RTE API Register', 'min_count': 1, 'max_count': 30,
        })

        cls.rte_admission = cls.env['op.admission'].create({
            'name': 'RTE Applicant One', 'first_name': 'RTE', 'last_name': 'One', 'gender': 'm',
            'birth_date': '2018-01-01', 'course_id': cls.course.id, 'email': 'rte.one@example.com',
            'register_id': cls.register.id, 'is_rte_applicant': True, 'rte_aadhaar_number': '123456789012',
            'partner_id': cls.parent_user.partner_id.id,
        })
        # A non-RTE (fee-paying) admission for the same course, required by
        # action_mark_ready's para-9 guard.
        cls.env['op.admission'].create({
            'name': 'Fee Paying Student', 'first_name': 'Fee', 'last_name': 'Payer', 'gender': 'f',
            'birth_date': '2018-01-01', 'course_id': cls.course.id, 'email': 'fee.payer@example.com',
            'register_id': cls.register.id, 'is_rte_applicant': False,
        })

    def _coord_headers(self):
        return self._headers('rte_api_coordinator', 'CoordPass1!')

    def _district_headers(self):
        return self._headers('rte_api_district', 'DistrictPass1!')

    def test_admissions_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/admissions/rte').status_code, 401)

    def test_parent_can_view_own_admission(self):
        resp = self.url_open(
            f'/api/v1/admissions/rte/{self.rte_admission.id}', headers=self._headers('rte_api_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['rte_state'], 'draft')

    def test_unrelated_user_cannot_view_admission(self):
        resp = self.url_open(
            f'/api/v1/admissions/rte/{self.rte_admission.id}', headers=self._headers('rte_api_other', 'OtherPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_verify_and_grievance_flow(self):
        coord_headers = self._coord_headers()
        verify = self.url_open(
            f'/api/v1/admissions/rte/{self.rte_admission.id}/verify-documents', headers=coord_headers, method='POST')
        self.assertEqual(verify.status_code, 200)
        self.assertEqual(verify.json()['data']['rte_state'], 'doc_verified')

        reject = self.url_open(
            f'/api/v1/admissions/rte/{self.rte_admission.id}/reject-documents', headers=coord_headers, json={
                'rejection_reason': 'Aadhaar photo unclear.',
            })
        self.assertEqual(reject.status_code, 200)
        self.assertEqual(reject.json()['data']['rte_state'], 'doc_rejected')

        grievance_resp = self.url_open(
            f'/api/v1/admissions/rte/{self.rte_admission.id}/grievances',
            headers=self._headers('rte_api_parent', 'ParentPass1!'),
            json={'description': 'The Aadhaar copy I submitted was clear.'})
        self.assertEqual(grievance_resp.status_code, 201)
        grievance = grievance_resp.json()['data']
        self.assertEqual(grievance['state'], 'submitted')

        resolve = self.url_open(
            f'/api/v1/admissions/rte/grievances/{grievance["id"]}/cbeo-resolve', headers=coord_headers, json={
                'cbeo_resolution_notes': 'Re-verified from original document; accepted.',
            })
        self.assertEqual(resolve.status_code, 200)
        self.assertEqual(resolve.json()['data']['state'], 'resolved')

    def test_grievance_missing_description_rejected(self):
        resp = self.url_open(
            f'/api/v1/admissions/rte/{self.rte_admission.id}/grievances',
            headers=self._headers('rte_api_parent', 'ParentPass1!'), json={}, method='POST')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_description')

    def test_lottery_full_flow(self):
        self.rte_admission.action_verify_documents()

        create = self.url_open('/api/v1/admissions/rte/lottery-batches', headers=self._district_headers(), json={
            'course_id': self.course.id, 'academic_year_id': self.academic_year.id,
        })
        self.assertEqual(create.status_code, 201)
        batch_id = create.json()['data']['id']

        ready = self.url_open(
            f'/api/v1/admissions/rte/lottery-batches/{batch_id}/mark-ready',
            headers=self._district_headers(), method='POST')
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()['data']['state'], 'ready')

        run = self.url_open(
            f'/api/v1/admissions/rte/lottery-batches/{batch_id}/run',
            headers=self._district_headers(), method='POST')
        self.assertEqual(run.status_code, 200)
        self.assertEqual(run.json()['data']['state'], 'run')
        self.assertEqual(len(run.json()['data']['results']), 1)
        self.assertEqual(run.json()['data']['results'][0]['result_type'], 'selected')

        publish = self.url_open(
            f'/api/v1/admissions/rte/lottery-batches/{batch_id}/publish',
            headers=self._district_headers(), method='POST')
        self.assertEqual(publish.status_code, 200)
        self.assertEqual(publish.json()['data']['state'], 'published')

        self.assertEqual(self.rte_admission.rte_state, 'allotted')

    def test_coordinator_cannot_access_lottery(self):
        resp = self.url_open('/api/v1/admissions/rte/lottery-batches', headers=self._coord_headers())
        self.assertEqual(resp.status_code, 403)

    def test_reimbursement_claim_lifecycle(self):
        headers = self._coord_headers()
        create = self.url_open('/api/v1/admissions/rte/reimbursement-claims', headers=headers, json={
            'course_id': self.course.id, 'academic_year_id': self.academic_year.id,
            'admission_id': self.rte_admission.id, 'installment': 'first', 'amount': 5000.0,
        })
        self.assertEqual(create.status_code, 201)
        claim_id = create.json()['data']['id']

        submit = self.url_open(
            f'/api/v1/admissions/rte/reimbursement-claims/{claim_id}/submit', headers=headers, method='POST')
        self.assertEqual(submit.status_code, 200)
        self.assertEqual(submit.json()['data']['state'], 'submitted')

        approve = self.url_open(
            f'/api/v1/admissions/rte/reimbursement-claims/{claim_id}/approve', headers=headers, method='POST')
        self.assertEqual(approve.status_code, 200)
        self.assertEqual(approve.json()['data']['state'], 'approved')

        paid = self.url_open(
            f'/api/v1/admissions/rte/reimbursement-claims/{claim_id}/mark-paid', headers=headers, method='POST')
        self.assertEqual(paid.status_code, 200)
        self.assertEqual(paid.json()['data']['state'], 'paid')
