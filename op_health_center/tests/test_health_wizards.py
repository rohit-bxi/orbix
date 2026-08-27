from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHealthWizards(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student = cls.env['op.student'].create({
            'first_name': 'Wendy', 'last_name': 'Wiz',
            'gr_no': 'HLTW-001', 'gender': 'f',
            'birth_date': '2013-06-20', 'blood_group': 'O+',
        })
        cls.vaccine_type = cls.env['op.health.vaccine.type'].create({
            'name': 'Polio', 'code': 'POL',
        })
        cls.checkup = cls.env['op.health.checkup'].create({
            'type': 'student', 'student_id': cls.student.id,
            'height_cm': 140.0, 'weight_kg': 35.0,
            'checkup_date': date(2026, 1, 15),
        })
        cls.checkup.action_complete()
        cls.vaccination = cls.env['op.health.vaccination'].create({
            'type': 'student', 'student_id': cls.student.id,
            'vaccine_id': cls.vaccine_type.id,
            'date_administered': date(2026, 2, 1),
        })
        cls.vaccination.action_complete()

    def test_certificate_wizard_print_returns_report_action(self):
        wizard = self.env['op.health.certificate.wizard'].create({
            'patient_type': 'student',
            'student_id': self.student.id,
            'certificate_type': 'general',
        })
        action = wizard.with_context(discard_logo_check=True).print_certificate()
        self.assertEqual(action.get('type'), 'ir.actions.report')

    def test_certificate_wizard_includes_latest_completed_checkup(self):
        wizard = self.env['op.health.certificate.wizard'].create({
            'patient_type': 'student',
            'student_id': self.student.id,
            'certificate_type': 'general',
        })
        action = wizard.with_context(discard_logo_check=True).print_certificate()
        report_data = action.get('data') or {}
        self.assertTrue(report_data.get('latest_checkup'))
        self.assertEqual(report_data['latest_checkup']['bmi_category'], 'Normal')

    def test_certificate_wizard_filters_vaccinations_by_date_range(self):
        wizard = self.env['op.health.certificate.wizard'].create({
            'patient_type': 'student',
            'student_id': self.student.id,
            'certificate_type': 'vaccination',
            'date_from': date(2026, 3, 1),
            'date_to': date(2026, 3, 31),
        })
        action = wizard.with_context(discard_logo_check=True).print_certificate()
        report_data = action.get('data') or {}
        self.assertEqual(report_data.get('vaccinations'), [])

    def test_visit_report_wizard_filters_by_patient_type(self):
        self.env['op.health.visit'].create({
            'type': 'student', 'student_id': self.student.id,
        })
        wizard = self.env['op.health.visit.report.wizard'].create({
            'date_from': date.today().replace(day=1),
            'date_to': date.today(),
            'patient_type': 'student',
        })
        action = wizard.with_context(discard_logo_check=True).visit_report()
        report_data = action.get('data') or {}
        self.assertEqual(len(report_data.get('all_data')), 1)

    def test_visit_report_wizard_empty_when_out_of_range(self):
        self.env['op.health.visit'].create({
            'type': 'student', 'student_id': self.student.id,
        })
        wizard = self.env['op.health.visit.report.wizard'].create({
            'date_from': date(2020, 1, 1),
            'date_to': date(2020, 1, 31),
            'patient_type': 'all',
        })
        action = wizard.with_context(discard_logo_check=True).visit_report()
        report_data = action.get('data') or {}
        self.assertEqual(report_data.get('all_data'), [])

    def test_dashboard_default_get_computes_kpis(self):
        self.env['op.health.visit'].create({
            'type': 'student', 'student_id': self.student.id,
        })
        dashboard = self.env['op.health.dashboard'].create({})
        self.assertGreaterEqual(dashboard.visit_count_today, 1)
        self.assertGreaterEqual(dashboard.visit_count_month, 1)
        self.assertGreater(dashboard.checkup_compliance_rate, 0.0)
