from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCertificate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.certificate_type = cls.env['op.certificate.type'].create({
            'name': 'Test Certificate',
            'code': 'TST',
        })
        cls.student = cls.env['op.student'].create({
            'first_name': 'Jane',
            'last_name': 'Doe',
            'gr_no': 'TST-001',
            'gender': 'f',
        })

    def test_sequence_created_on_type(self):
        self.assertTrue(self.certificate_type.sequence_id)
        self.assertEqual(self.certificate_type.sequence_id.code, 'op.certificate.tst')

    def test_generate_and_issue_flow(self):
        certificate = self.env['op.certificate'].create({
            'certificate_type_id': self.certificate_type.id,
            'student_id': self.student.id,
        })
        self.assertEqual(certificate.state, 'draft')
        certificate.action_generate()
        self.assertEqual(certificate.state, 'generated')
        self.assertTrue(certificate.certificate_number)
        certificate.action_issue()
        self.assertEqual(certificate.state, 'issued')
        self.assertTrue(certificate.attachment_id)

    def test_approval_required_blocks_issue(self):
        approval_type = self.env['op.certificate.type'].create({
            'name': 'Approval Required',
            'code': 'APR',
            'requires_approval': True,
        })
        certificate = self.env['op.certificate'].create({
            'certificate_type_id': approval_type.id,
            'student_id': self.student.id,
        })
        certificate.action_generate()
        with self.assertRaises(UserError):
            certificate.action_issue()
        certificate.action_approve()
        certificate.action_issue()
        self.assertEqual(certificate.state, 'issued')

    def test_expiry_computed(self):
        validity_type = self.env['op.certificate.type'].create({
            'name': 'Time Limited',
            'code': 'TL',
            'validity_months': 6,
        })
        certificate = self.env['op.certificate'].create({
            'certificate_type_id': validity_type.id,
            'student_id': self.student.id,
            'issue_date': '2026-01-01',
        })
        self.assertEqual(str(certificate.expiry_date), '2026-07-01')

    def test_revoke_records_reason(self):
        certificate = self.env['op.certificate'].create({
            'certificate_type_id': self.certificate_type.id,
            'student_id': self.student.id,
        })
        certificate.action_generate()
        certificate.action_issue()
        certificate.action_revoke('Issued in error')
        self.assertEqual(certificate.state, 'revoked')
        self.assertEqual(certificate.revoke_reason, 'Issued in error')

    def test_verification_code_unique(self):
        cert_1 = self.env['op.certificate'].create({
            'certificate_type_id': self.certificate_type.id,
            'student_id': self.student.id,
        })
        cert_2 = self.env['op.certificate'].create({
            'certificate_type_id': self.certificate_type.id,
            'student_id': self.student.id,
        })
        self.assertNotEqual(cert_1.verification_code, cert_2.verification_code)
