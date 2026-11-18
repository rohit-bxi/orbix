# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportCertificate(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.staff_user = mail_new_test_user(
            cls.env, login='cert_api_staff',
            groups='base.group_user,bxi_certificate_management.group_certificate_user',
            password='StaffPass1!')
        cls.manager_user = mail_new_test_user(
            cls.env, login='cert_api_manager',
            groups='base.group_user,bxi_certificate_management.group_certificate_manager',
            password='ManagerPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='cert_api_other', groups='base.group_user', password='OtherPass1!')
        cls.student_user = mail_new_test_user(
            cls.env, login='cert_api_student', groups='base.group_user', password='StudentPass1!')
        cls.student = cls._create_student('CERTAPI-001', user=cls.student_user)

        cls.cert_type = cls.env['op.certificate.type'].create({'name': 'API Bonafide', 'code': 'API-BONA'})
        cls.approval_cert_type = cls.env['op.certificate.type'].create({
            'name': 'API Transfer Certificate', 'code': 'API-TC', 'requires_approval': True,
        })

    def _staff_headers(self):
        return self._headers('cert_api_staff', 'StaffPass1!')

    def test_certificates_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/certificates').status_code, 401)

    def test_staff_full_generate_issue_flow(self):
        headers = self._staff_headers()
        create = self.url_open('/api/v1/certificates', headers=headers, json={
            'student_id': self.student.id, 'certificate_type_id': self.cert_type.id,
        })
        self.assertEqual(create.status_code, 201)
        cert_id = create.json()['data']['id']

        generate = self.url_open(f'/api/v1/certificates/{cert_id}/generate', headers=headers, method='POST')
        self.assertEqual(generate.status_code, 200)
        self.assertEqual(generate.json()['data']['state'], 'generated')
        self.assertTrue(generate.json()['data']['certificate_number'])

        issue = self.url_open(f'/api/v1/certificates/{cert_id}/issue', headers=headers, method='POST')
        self.assertEqual(issue.status_code, 200)
        self.assertEqual(issue.json()['data']['state'], 'issued')

    def test_issue_requires_approval_when_type_demands_it(self):
        headers = self._staff_headers()
        create = self.url_open('/api/v1/certificates', headers=headers, json={
            'student_id': self.student.id, 'certificate_type_id': self.approval_cert_type.id,
        })
        cert_id = create.json()['data']['id']
        self.url_open(f'/api/v1/certificates/{cert_id}/generate', headers=headers, method='POST')

        issue_before_approval = self.url_open(f'/api/v1/certificates/{cert_id}/issue', headers=headers, method='POST')
        self.assertEqual(issue_before_approval.status_code, 400)
        self.assertEqual(issue_before_approval.json()['error']['code'], 'invalid_transition')

        approve = self.url_open(
            f'/api/v1/certificates/{cert_id}/approve', headers=self._headers('cert_api_manager', 'ManagerPass1!'),
            method='POST')
        self.assertEqual(approve.status_code, 200)

        issue_after_approval = self.url_open(f'/api/v1/certificates/{cert_id}/issue', headers=headers, method='POST')
        self.assertEqual(issue_after_approval.status_code, 200)
        self.assertEqual(issue_after_approval.json()['data']['state'], 'issued')

    def test_staff_cannot_approve_only_manager_can(self):
        headers = self._staff_headers()
        create = self.url_open('/api/v1/certificates', headers=headers, json={
            'student_id': self.student.id, 'certificate_type_id': self.approval_cert_type.id,
        })
        cert_id = create.json()['data']['id']
        resp = self.url_open(f'/api/v1/certificates/{cert_id}/approve', headers=headers, method='POST')
        self.assertEqual(resp.status_code, 403)

    def test_revoke_requires_reason_and_manager(self):
        headers = self._staff_headers()
        create = self.url_open('/api/v1/certificates', headers=headers, json={
            'student_id': self.student.id, 'certificate_type_id': self.cert_type.id,
        })
        cert_id = create.json()['data']['id']

        forbidden = self.url_open(f'/api/v1/certificates/{cert_id}/revoke', headers=headers, json={'reason': 'x'})
        self.assertEqual(forbidden.status_code, 403)

        manager_headers = self._headers('cert_api_manager', 'ManagerPass1!')
        missing_reason = self.url_open(f'/api/v1/certificates/{cert_id}/revoke', headers=manager_headers, json={}, method='POST')
        self.assertEqual(missing_reason.status_code, 400)

        revoke = self.url_open(
            f'/api/v1/certificates/{cert_id}/revoke', headers=manager_headers, json={'reason': 'Issued in error.'})
        self.assertEqual(revoke.status_code, 200)
        self.assertEqual(revoke.json()['data']['state'], 'revoked')

    def test_verify_endpoint_is_public(self):
        headers = self._staff_headers()
        create = self.url_open('/api/v1/certificates', headers=headers, json={
            'student_id': self.student.id, 'certificate_type_id': self.cert_type.id,
        })
        cert_id = create.json()['data']['id']
        self.url_open(f'/api/v1/certificates/{cert_id}/generate', headers=headers, method='POST')
        self.url_open(f'/api/v1/certificates/{cert_id}/issue', headers=headers, method='POST')
        cert = self.env['op.certificate'].sudo().browse(cert_id)

        resp = self.url_open(f'/api/v1/certificates/verify?code={cert.verification_code}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['status'], 'valid')

        not_found = self.url_open('/api/v1/certificates/verify?code=does-not-exist')
        self.assertEqual(not_found.status_code, 200)
        self.assertEqual(not_found.json()['data']['status'], 'not_found')

    def test_student_only_sees_own_issued_certificates(self):
        headers = self._staff_headers()
        create = self.url_open('/api/v1/certificates', headers=headers, json={
            'student_id': self.student.id, 'certificate_type_id': self.cert_type.id,
        })
        cert_id = create.json()['data']['id']

        student_headers = self._headers('cert_api_student', 'StudentPass1!')
        before_issue = self.url_open('/api/v1/certificates', headers=student_headers).json()['data']['certificates']
        self.assertEqual(len(before_issue), 0)

        self.url_open(f'/api/v1/certificates/{cert_id}/generate', headers=headers, method='POST')
        self.url_open(f'/api/v1/certificates/{cert_id}/issue', headers=headers, method='POST')

        after_issue = self.url_open('/api/v1/certificates', headers=student_headers).json()['data']['certificates']
        self.assertEqual(len(after_issue), 1)

    def test_other_user_cannot_create_certificates(self):
        resp = self.url_open('/api/v1/certificates', headers=self._headers('cert_api_other', 'OtherPass1!'), json={
            'student_id': self.student.id, 'certificate_type_id': self.cert_type.id,
        })
        self.assertEqual(resp.status_code, 403)

    def _generated(self, cert_type=None):
        headers = self._staff_headers()
        cert_id = self.url_open('/api/v1/certificates', headers=headers, json={
            'student_id': self.student.id, 'certificate_type_id': (cert_type or self.cert_type).id,
        }).json()['data']['id']
        self.url_open(f'/api/v1/certificates/{cert_id}/generate', headers=headers, method='POST')
        return cert_id

    def test_reset_to_draft(self):
        cert_id = self._generated()
        url = f'/api/v1/certificates/{cert_id}/reset'
        self.assertEqual(self.url_open(url, headers=self._headers('cert_api_student', 'StudentPass1!'),
                                       method='POST').status_code, 403)
        reset = self.url_open(url, headers=self._staff_headers(), method='POST')
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(reset.json()['data']['state'], 'draft')
        self.assertFalse(reset.json()['data']['certificate_number'])
        self.assertEqual(self.url_open('/api/v1/certificates/999999/reset', headers=self._staff_headers(),
                                       method='POST').status_code, 404)

    def test_issued_certificate_cannot_be_reset(self):
        cert_id = self._generated()
        self.url_open(f'/api/v1/certificates/{cert_id}/issue', headers=self._staff_headers(), method='POST')
        resp = self.url_open(f'/api/v1/certificates/{cert_id}/reset', headers=self._staff_headers(), method='POST')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'invalid_transition')
        cert = self.env['op.certificate'].browse(cert_id)
        self.assertEqual(cert.state, 'issued')
        self.assertTrue(cert.certificate_number)

    def test_pdf_download(self):
        cert_id = self._generated()
        student = self._headers('cert_api_student', 'StudentPass1!')
        url = f'/api/v1/certificates/{cert_id}/pdf'
        # Families only see it once issued; staff get no_pdf until then.
        self.assertEqual(self.url_open(url, headers=student).status_code, 403)
        self.assertEqual(self.url_open(url, headers=self._staff_headers()).json()['error']['code'], 'no_pdf')
        self.url_open(f'/api/v1/certificates/{cert_id}/issue', headers=self._staff_headers(), method='POST')
        resp = self.url_open(url, headers=student)
        self.assertEqual(resp.status_code, 200, resp.text[:300])
        self.assertTrue(resp.content)
        self.assertIn('attachment', resp.headers.get('Content-Disposition', ''))
        self.assertEqual(self.url_open(url, headers=self._headers('cert_api_other', 'OtherPass1!')).status_code, 403)

    def test_bulk_create(self):
        second = self._create_student('CERTAPI-002')
        payload = {'certificate_type_id': self.cert_type.id, 'student_ids': [self.student.id, second.id]}
        self.assertEqual(self.url_open('/api/v1/certificates/bulk-create', json=payload,
                                       headers=self._headers('cert_api_other', 'OtherPass1!')).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/certificates/bulk-create', headers=self._staff_headers(), json={
            'certificate_type_id': self.cert_type.id}).json()['error']['code'], 'missing_student_ids')
        resp = self.url_open('/api/v1/certificates/bulk-create', headers=self._staff_headers(), json=payload)
        self.assertEqual(resp.status_code, 201, resp.text)
        certs = resp.json()['data']['certificates']
        self.assertEqual(sorted(c['student_id'] for c in certs), sorted([self.student.id, second.id]))
        self.assertEqual({c['state'] for c in certs}, {'draft'})
        self.assertEqual({c['certificate_type'] for c in certs}, {'API Bonafide'})

    def test_certificate_detail(self):
        cert_id = self._generated()
        staff = self.url_open(f'/api/v1/certificates/{cert_id}', headers=self._staff_headers())
        self.assertEqual(staff.status_code, 200, staff.text)
        self.assertEqual((staff.json()['data']['state'], staff.json()['data']['student_id']), ('generated', self.student.id))
        student = self._headers('cert_api_student', 'StudentPass1!')
        self.assertEqual(self.url_open(f'/api/v1/certificates/{cert_id}', headers=student).status_code, 403)
        self.url_open(f'/api/v1/certificates/{cert_id}/issue', headers=self._staff_headers(), method='POST')
        issued = self.url_open(f'/api/v1/certificates/{cert_id}', headers=student)
        self.assertEqual(issued.status_code, 200, issued.text)
        self.assertEqual(issued.json()['data']['state'], 'issued')
