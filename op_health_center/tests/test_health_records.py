from datetime import date, datetime, timedelta

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHealthRecords(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student = cls.env['op.student'].create({
            'first_name': 'Ivy', 'last_name': 'Nurse',
            'gr_no': 'HLT-001', 'gender': 'f',
            'birth_date': '2012-04-15',
        })
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Frank', 'last_name': 'Mentor',
            'birth_date': '1980-01-01', 'gender': 'male',
        })
        health_group = cls.env.ref('op_health_center.group_health_staff')
        cls.health_user = cls.env['res.users'].create({
            'name': 'Nurse Joy', 'login': 'nurse.joy.test',
            'group_ids': [(4, health_group.id)],
        })
        cls.health_employee = cls.env['hr.employee'].create({
            'name': 'Nurse Joy', 'user_id': cls.health_user.id,
            'health_role': 'nurse',
        })
        cls.vaccine_type = cls.env['op.health.vaccine.type'].create({
            'name': 'Tetanus', 'code': 'TET', 'doses_required': 2,
        })

    # -- patient mixin -----------------------------------------------

    def test_patient_mixin_rejects_both_student_and_faculty(self):
        with self.assertRaises(ValidationError):
            self.env['op.health.visit'].create({
                'type': 'student',
                'student_id': self.student.id,
                'faculty_id': self.faculty.id,
            })

    def test_patient_mixin_rejects_neither(self):
        with self.assertRaises(ValidationError):
            self.env['op.health.visit'].create({'type': 'student'})

    def test_patient_mixin_computes_type_and_name_for_student(self):
        visit = self.env['op.health.visit'].create({
            'type': 'student', 'student_id': self.student.id,
        })
        self.assertEqual(visit.patient_type, 'student')
        self.assertEqual(visit.patient_name, self.student.name)

    # -- health visit --------------------------------------------------

    def test_visit_sequence_assigned_on_create(self):
        visit = self.env['op.health.visit'].create({
            'type': 'student', 'student_id': self.student.id,
        })
        self.assertNotEqual(visit.name, 'New')
        self.assertTrue(visit.name)

    def test_visit_follow_up_requires_date(self):
        visit = self.env['op.health.visit'].create({
            'type': 'student', 'student_id': self.student.id,
            'visit_datetime': datetime(2026, 9, 1, 10, 0),
        })
        with self.assertRaises(ValidationError):
            visit.write({'follow_up_required': True})

    def test_visit_follow_up_date_cannot_precede_visit_date(self):
        visit = self.env['op.health.visit'].create({
            'type': 'student', 'student_id': self.student.id,
            'visit_datetime': datetime(2026, 9, 5, 10, 0),
        })
        with self.assertRaises(ValidationError):
            visit.write({
                'follow_up_required': True,
                'follow_up_date': date(2026, 9, 1),
            })

    def test_visit_follow_up_date_after_visit_date_allowed(self):
        visit = self.env['op.health.visit'].create({
            'type': 'student', 'student_id': self.student.id,
            'visit_datetime': datetime(2026, 9, 5, 10, 0),
        })
        visit.write({
            'follow_up_required': True,
            'follow_up_date': date(2026, 9, 10),
        })
        self.assertEqual(visit.follow_up_date, date(2026, 9, 10))

    def test_visit_state_workflow(self):
        visit = self.env['op.health.visit'].create({
            'type': 'student', 'student_id': self.student.id,
        })
        self.assertEqual(visit.state, 'draft')
        visit.action_confirm()
        self.assertEqual(visit.state, 'confirmed')
        visit.action_start_treatment()
        self.assertEqual(visit.state, 'under_treatment')
        visit.action_resolve()
        self.assertEqual(visit.state, 'resolved')
        visit.action_refer()
        self.assertEqual(visit.state, 'referred')
        visit.action_cancel()
        self.assertEqual(visit.state, 'cancelled')
        visit.action_reset_draft()
        self.assertEqual(visit.state, 'draft')

    def test_visit_onchange_type_clears_other_patient(self):
        visit = self.env['op.health.visit'].new({
            'type': 'student', 'student_id': self.student.id,
        })
        visit.type = 'teacher'
        visit._onchange_type()
        self.assertFalse(visit.student_id)

    # -- vaccination -----------------------------------------------------

    def test_vaccination_sequence_assigned_on_create(self):
        vaccination = self.env['op.health.vaccination'].create({
            'type': 'student', 'student_id': self.student.id,
            'vaccine_id': self.vaccine_type.id,
        })
        self.assertNotEqual(vaccination.name, 'New')

    def test_vaccination_complete_requires_date_administered(self):
        vaccination = self.env['op.health.vaccination'].create({
            'type': 'student', 'student_id': self.student.id,
            'vaccine_id': self.vaccine_type.id,
        })
        with self.assertRaises(ValidationError):
            vaccination.write({'state': 'completed'})

    def test_vaccination_action_complete_sets_default_date(self):
        vaccination = self.env['op.health.vaccination'].create({
            'type': 'student', 'student_id': self.student.id,
            'vaccine_id': self.vaccine_type.id,
        })
        vaccination.action_complete()
        self.assertEqual(vaccination.state, 'completed')
        self.assertTrue(vaccination.date_administered)

    def test_vaccination_cron_flags_overdue_as_missed(self):
        today = date.today()
        vaccination = self.env['op.health.vaccination'].create({
            'type': 'student', 'student_id': self.student.id,
            'vaccine_id': self.vaccine_type.id,
            'next_due_date': today - timedelta(days=5),
        })
        self.env['op.health.vaccination']._cron_flag_overdue_vaccinations()
        self.assertEqual(vaccination.state, 'missed')

    def test_vaccination_cron_ignores_future_due_dates(self):
        today = date.today()
        vaccination = self.env['op.health.vaccination'].create({
            'type': 'student', 'student_id': self.student.id,
            'vaccine_id': self.vaccine_type.id,
            'next_due_date': today + timedelta(days=5),
        })
        self.env['op.health.vaccination']._cron_flag_overdue_vaccinations()
        self.assertEqual(vaccination.state, 'scheduled')

    # -- checkup -----------------------------------------------------

    def test_checkup_bmi_and_category_computed(self):
        checkup = self.env['op.health.checkup'].create({
            'type': 'student', 'student_id': self.student.id,
            'height_cm': 150.0, 'weight_kg': 45.0,
        })
        self.assertAlmostEqual(checkup.bmi, 20.0, places=1)
        self.assertEqual(checkup.bmi_category, 'normal')

    def test_checkup_bmi_category_underweight(self):
        checkup = self.env['op.health.checkup'].create({
            'type': 'student', 'student_id': self.student.id,
            'height_cm': 170.0, 'weight_kg': 45.0,
        })
        self.assertEqual(checkup.bmi_category, 'underweight')

    def test_checkup_rejects_non_positive_height(self):
        with self.assertRaises(ValidationError):
            self.env['op.health.checkup'].create({
                'type': 'student', 'student_id': self.student.id,
                'height_cm': -10.0,
            })

    def test_checkup_state_workflow(self):
        checkup = self.env['op.health.checkup'].create({
            'type': 'student', 'student_id': self.student.id,
        })
        self.assertEqual(checkup.state, 'scheduled')
        checkup.action_complete()
        self.assertEqual(checkup.state, 'completed')
        checkup.action_cancel()
        self.assertEqual(checkup.state, 'cancelled')
        checkup.action_reset()
        self.assertEqual(checkup.state, 'scheduled')

    # -- student/faculty health profile ------------------------------

    def test_student_medical_alert_computed_from_chronic_conditions(self):
        self.student.chronic_conditions = 'Asthma'
        self.assertTrue(self.student.medical_alert)

    def test_faculty_medical_alert_computed_from_allergy_flag(self):
        self.faculty.is_allergy = True
        self.assertTrue(self.faculty.medical_alert)

    def test_student_health_counts_computed(self):
        self.env['op.health.visit'].create({
            'type': 'student', 'student_id': self.student.id,
        })
        self.env['op.health.vaccination'].create({
            'type': 'student', 'student_id': self.student.id,
            'vaccine_id': self.vaccine_type.id,
        })
        self.assertEqual(self.student.visit_count, 1)
        self.assertEqual(self.student.vaccination_count, 1)

    def test_student_last_checkup_date_only_counts_completed(self):
        checkup = self.env['op.health.checkup'].create({
            'type': 'student', 'student_id': self.student.id,
            'checkup_date': date(2026, 3, 1),
        })
        self.assertFalse(self.student.last_checkup_date)
        checkup.action_complete()
        self.assertEqual(self.student.last_checkup_date, date(2026, 3, 1))

    # -- health staff --------------------------------------------------

    def test_is_health_staff_true_for_group_member(self):
        self.assertTrue(self.health_employee.is_health_staff)

    def test_is_health_staff_false_for_non_member(self):
        plain_employee = self.env['hr.employee'].create({'name': 'Regular Staff'})
        self.assertFalse(plain_employee.is_health_staff)
