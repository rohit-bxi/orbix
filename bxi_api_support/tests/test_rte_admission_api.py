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

    def _parent_headers(self):
        return self._headers('rte_api_parent', 'ParentPass1!')

    def _grievance(self):
        self.rte_admission.action_reject_documents()
        return self.rte_admission.action_file_grievance('The documents were complete.')

    def test_grievance_detail_access(self):
        grievance = self._grievance()
        url = f'/api/v1/admissions/rte/grievances/{grievance.id}'
        own = self.url_open(url, headers=self._parent_headers())
        self.assertEqual(own.status_code, 200, own.text)
        self.assertEqual(own.json()['data']['admission_id'], self.rte_admission.id)
        self.assertEqual(own.json()['data']['state'], 'submitted')
        self.assertEqual(self.url_open(url, headers=self._coord_headers()).status_code, 200)
        self.assertEqual(self.url_open(url, headers=self._headers('rte_api_other', 'OtherPass1!')).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/admissions/rte/grievances/999999',
                                       headers=self._coord_headers()).status_code, 404)

    def test_grievance_escalate_and_jd_resolve(self):
        grievance = self._grievance()
        base = f'/api/v1/admissions/rte/grievances/{grievance.id}'
        self.assertEqual(self.url_open(f'{base}/escalate', headers=self._parent_headers(), method='POST').status_code, 403)
        # JD resolution only applies once escalated.
        early = self.url_open(f'{base}/jd-resolve', headers=self._district_headers(),
                              json={'jd_resolution_notes': 'Too early.'})
        self.assertEqual(early.status_code, 400)
        self.assertFalse(grievance.jd_resolution_notes)  # a refused call doesn't keep its notes

        escalated = self.url_open(f'{base}/escalate', headers=self._coord_headers(), method='POST')
        self.assertEqual(escalated.status_code, 200, escalated.text)
        self.assertEqual(escalated.json()['data']['state'], 'escalated_jd')
        self.assertEqual(self.url_open(f'{base}/escalate', headers=self._coord_headers(), method='POST').status_code, 400)

        # A school coordinator can't resolve at Joint Director level.
        self.assertEqual(self.url_open(f'{base}/jd-resolve', headers=self._coord_headers(),
                                       json={'jd_resolution_notes': 'x'}).status_code, 403)
        # Also a body-less POST: this used to crash with a 500.
        no_notes = self.url_open(f'{base}/jd-resolve', headers=self._district_headers(), method='POST')
        self.assertEqual(no_notes.status_code, 400)
        resolved = self.url_open(f'{base}/jd-resolve', headers=self._district_headers(),
                                 json={'jd_resolution_notes': 'Documents re-checked; accepted.'})
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()['data']['state'], 'resolved')
        self.assertEqual(resolved.json()['data']['jd_resolution_notes'], 'Documents re-checked; accepted.')

    def test_grievance_reject(self):
        grievance = self._grievance()
        url = f'/api/v1/admissions/rte/grievances/{grievance.id}/reject'
        self.assertEqual(self.url_open(url, headers=self._parent_headers(), method='POST').status_code, 403)
        rejected = self.url_open(url, headers=self._coord_headers(), method='POST')
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(rejected.json()['data']['state'], 'rejected')
        self.assertEqual(self.url_open(url, headers=self._coord_headers(), method='POST').status_code, 400)

    def test_lottery_create_and_run_and_detail(self):
        self.rte_admission.action_verify_documents()
        payload = {'course_id': self.course.id, 'academic_year_id': self.academic_year.id}
        url = '/api/v1/admissions/rte/lottery-batches/create-and-run'
        self.assertEqual(self.url_open(url, headers=self._coord_headers(), json=payload).status_code, 403)
        self.assertEqual(self.url_open(url, headers=self._district_headers(), json={'course_id': self.course.id})
                         .json()['error']['code'], 'missing_academic_year_id')
        resp = self.url_open(url, headers=self._district_headers(), json=payload)
        self.assertEqual(resp.status_code, 201, resp.text)
        batch = resp.json()['data']
        self.assertEqual(batch['state'], 'run')
        self.assertEqual([(r['admission_id'], r['result_type']) for r in batch['results']],
                         [(self.rte_admission.id, 'selected')])

        detail = self.url_open(f"/api/v1/admissions/rte/lottery-batches/{batch['id']}", headers=self._district_headers())
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['data']['results'], batch['results'])
        self.assertEqual(self.url_open(f"/api/v1/admissions/rte/lottery-batches/{batch['id']}",
                                       headers=self._coord_headers()).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/admissions/rte/lottery-batches/999999',
                                       headers=self._district_headers()).status_code, 404)

    def test_confirm_then_mark_admitted(self):
        base = f'/api/v1/admissions/rte/{self.rte_admission.id}'
        # Nothing to confirm or admit while still a draft application.
        self.assertEqual(self.url_open(f'{base}/confirm', headers=self._parent_headers(), method='POST').status_code, 400)
        self.assertEqual(self.url_open(f'{base}/mark-admitted', headers=self._coord_headers(), method='POST').status_code, 400)

        self.rte_admission.rte_state = 'allotted'
        self.assertEqual(self.url_open(f'{base}/confirm', headers=self._headers('rte_api_other', 'OtherPass1!'),
                                       method='POST').status_code, 403)
        confirmed = self.url_open(f'{base}/confirm', headers=self._parent_headers(), method='POST')
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()['data']['rte_state'], 'confirmed')

        self.assertEqual(self.url_open(f'{base}/mark-admitted', headers=self._parent_headers(), method='POST').status_code, 403)
        admitted = self.url_open(f'{base}/mark-admitted', headers=self._coord_headers(), method='POST')
        self.assertEqual(admitted.status_code, 200, admitted.text)
        self.assertEqual(admitted.json()['data']['rte_state'], 'admitted')
        # An admitted child can no longer lapse.
        self.assertEqual(self.url_open(f'{base}/mark-lapsed', headers=self._coord_headers(), method='POST').status_code, 400)

    def test_mark_lapsed(self):
        base = f'/api/v1/admissions/rte/{self.rte_admission.id}'
        self.assertEqual(self.url_open(f'{base}/mark-lapsed', headers=self._coord_headers(), method='POST').status_code, 400)
        self.rte_admission.rte_state = 'allotted'
        self.assertEqual(self.url_open(f'{base}/mark-lapsed', headers=self._parent_headers(), method='POST').status_code, 403)
        lapsed = self.url_open(f'{base}/mark-lapsed', headers=self._coord_headers(), method='POST')
        self.assertEqual(lapsed.status_code, 200, lapsed.text)
        self.assertEqual(lapsed.json()['data']['rte_state'], 'lapsed')
        self.assertEqual(self.url_open('/api/v1/admissions/rte/999999/mark-lapsed',
                                       headers=self._coord_headers(), method='POST').status_code, 404)

    def test_claim_detail_and_reject(self):
        headers = self._coord_headers()
        claim_id = self.url_open('/api/v1/admissions/rte/reimbursement-claims', headers=headers, json={
            'course_id': self.course.id, 'academic_year_id': self.academic_year.id,
            'admission_id': self.rte_admission.id, 'installment': 'first', 'amount': 5000.0,
        }).json()['data']['id']
        base = f'/api/v1/admissions/rte/reimbursement-claims/{claim_id}'
        detail = self.url_open(base, headers=headers)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['data']['amount'], 5000.0)
        self.assertEqual(detail.json()['data']['state'], 'draft')
        self.assertEqual(self.url_open(base, headers=self._parent_headers()).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/admissions/rte/reimbursement-claims/999999', headers=headers).status_code, 404)

        # A draft claim can't be rejected; a submitted one can, once.
        self.assertEqual(self.url_open(f'{base}/reject', headers=headers, method='POST').status_code, 400)
        self.url_open(f'{base}/submit', headers=headers, method='POST')
        self.assertEqual(self.url_open(f'{base}/reject', headers=self._parent_headers(), method='POST').status_code, 403)
        rejected = self.url_open(f'{base}/reject', headers=headers, method='POST')
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(rejected.json()['data']['state'], 'rejected')
        self.assertEqual(self.url_open(f'{base}/mark-paid', headers=headers, method='POST').status_code, 400)

    def test_lists(self):
        coord = self._coord_headers()
        admissions = self.url_open('/api/v1/admissions/rte', headers=coord)
        self.assertEqual(admissions.status_code, 200, admissions.text)
        self.assertIn(self.rte_admission.id, [a['id'] for a in admissions.json()['data']['admissions']])
        own = self.url_open('/api/v1/admissions/rte', headers=self._parent_headers()).json()['data']['admissions']
        self.assertEqual([a['id'] for a in own], [self.rte_admission.id])

        grievance = self._grievance()
        grievances = self.url_open(f'/api/v1/admissions/rte/{self.rte_admission.id}/grievances', headers=self._parent_headers())
        self.assertEqual(grievances.status_code, 200, grievances.text)
        self.assertEqual([g['id'] for g in grievances.json()['data']['grievances']], [grievance.id])

        claim_id = self.url_open('/api/v1/admissions/rte/reimbursement-claims', headers=coord, json={
            'course_id': self.course.id, 'academic_year_id': self.academic_year.id, 'amount': 100.0}).json()['data']['id']
        claims = self.url_open('/api/v1/admissions/rte/reimbursement-claims', headers=coord)
        self.assertIn(claim_id, [c['id'] for c in claims.json()['data']['claims']])
        self.assertEqual(self.url_open('/api/v1/admissions/rte/reimbursement-claims',
                                       headers=self._parent_headers()).status_code, 403)

        batch = self.env['rte.lottery.batch'].create({'course_id': self.course.id, 'academic_year_id': self.academic_year.id})
        batches = self.url_open('/api/v1/admissions/rte/lottery-batches', headers=self._district_headers())
        self.assertEqual(batches.status_code, 200, batches.text)
        self.assertIn(batch.id, [b['id'] for b in batches.json()['data']['batches']])
