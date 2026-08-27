from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLabEquipment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({
            'name': 'Equip Course', 'code': 'EQC',
        })
        cls.batch = cls.env['op.batch'].create({
            'name': 'Equip Batch', 'code': 'EQB',
            'course_id': cls.course.id,
            'start_date': '2026-06-01', 'end_date': '2027-05-31',
        })
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Grace', 'last_name': 'Hopper',
            'birth_date': '1975-01-01', 'gender': 'female',
        })
        cls.room = cls.env['lab.room'].create({
            'name': 'Computer Lab', 'code': 'CMP-1',
        })
        cls.student = cls.env['op.student'].create({
            'first_name': 'Eli', 'last_name': 'Three',
            'gr_no': 'EQ-001', 'gender': 'm',
        })
        cls.equipment = cls.env['lab.equipment'].create({
            'name': 'Multimeter', 'lab_id': cls.room.id,
            'quantity_total': 5,
        })
        cls.session = cls.env['lab.session'].create({
            'room_id': cls.room.id, 'course_id': cls.course.id,
            'batch_id': cls.batch.id, 'faculty_id': cls.faculty.id,
            'date': '2026-09-01', 'start_time': 9.0, 'end_time': 10.0,
        })
        cls.experiment = cls.env['lab.experiment'].create({
            'name': 'Ohm\'s Law', 'max_marks': 50.0,
        })

    # -- equipment availability -------------------------------------

    def test_quantity_available_reduced_by_open_issue(self):
        self.env['lab.equipment.issue'].create({
            'session_id': self.session.id, 'equipment_id': self.equipment.id,
            'issued_qty': 2,
        })
        self.assertEqual(self.equipment.quantity_issued, 2)
        self.assertEqual(self.equipment.quantity_available, 3)

    def test_quantity_available_restored_after_full_return(self):
        issue = self.env['lab.equipment.issue'].create({
            'session_id': self.session.id, 'equipment_id': self.equipment.id,
            'issued_qty': 2,
        })
        issue.returned_qty = 2
        issue.action_return()
        self.assertEqual(issue.state, 'returned')
        self.assertEqual(self.equipment.quantity_available, 5)

    def test_partial_return_keeps_qty_reserved(self):
        issue = self.env['lab.equipment.issue'].create({
            'session_id': self.session.id, 'equipment_id': self.equipment.id,
            'issued_qty': 4,
        })
        issue.returned_qty = 1
        issue.action_return()
        self.assertEqual(issue.state, 'partial')
        self.assertEqual(self.equipment.quantity_available, 2)

    def test_cannot_issue_more_than_available(self):
        with self.assertRaises(ValidationError):
            self.env['lab.equipment.issue'].create({
                'session_id': self.session.id, 'equipment_id': self.equipment.id,
                'issued_qty': 6,
            })

    def test_double_booking_of_full_stock_blocked(self):
        self.env['lab.equipment.issue'].create({
            'session_id': self.session.id, 'equipment_id': self.equipment.id,
            'issued_qty': 5,
        })
        self.assertEqual(self.equipment.quantity_available, 0)
        with self.assertRaises(ValidationError):
            self.env['lab.equipment.issue'].create({
                'session_id': self.session.id, 'equipment_id': self.equipment.id,
                'issued_qty': 1,
            })

    def test_mark_damaged_sets_state(self):
        issue = self.env['lab.equipment.issue'].create({
            'session_id': self.session.id, 'equipment_id': self.equipment.id,
            'issued_qty': 1,
        })
        issue.action_mark_damaged()
        self.assertEqual(issue.state, 'damaged')
        # Only 'issued'/'partial' lines count against availability, so a
        # damaged (closed) line frees its quantity back up again.
        self.assertEqual(self.equipment.quantity_available, 5)

    # -- experiment result grading -----------------------------------

    def test_experiment_result_grade_a_plus(self):
        result = self.env['lab.experiment.result'].create({
            'session_id': self.session.id, 'experiment_id': self.experiment.id,
            'student_id': self.student.id, 'marks_obtained': 48.0,
        })
        self.assertEqual(result.grade, 'A+')

    def test_experiment_result_grade_fail(self):
        result = self.env['lab.experiment.result'].create({
            'session_id': self.session.id, 'experiment_id': self.experiment.id,
            'student_id': self.student.id, 'marks_obtained': 10.0,
        })
        self.assertEqual(result.grade, 'F')

    def test_experiment_result_grade_boundary_c(self):
        result = self.env['lab.experiment.result'].create({
            'session_id': self.session.id, 'experiment_id': self.experiment.id,
            'student_id': self.student.id, 'marks_obtained': 30.0,  # 60%
        })
        self.assertEqual(result.grade, 'C')
