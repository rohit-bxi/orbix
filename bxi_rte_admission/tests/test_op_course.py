# -*- coding: utf-8 -*-

from odoo.tests.common import tagged
from odoo.exceptions import ValidationError

from .common import TestRteAdmissionCommon


@tagged('post_install', '-at_install')
class TestOpCourse(TestRteAdmissionCommon):

    def test_rte_seats_computed_as_25_percent_of_intake(self):
        # _compute_rte_seats does floor(total_intake * 0.25 + 0.5) -- round half up.
        course = self.env['op.course'].create({
            'name': 'Course A', 'code': 'CA01', 'total_intake': 40,
        })
        self.assertEqual(course.rte_seats, 10)

    def test_rte_seats_rounding_matches_python_round(self):
        # 21 * 0.25 = 5.25 -> rounds down to 5 either way.
        course = self.env['op.course'].create({
            'name': 'Course B', 'code': 'CB01', 'total_intake': 21,
        })
        self.assertEqual(course.rte_seats, 5)

    def test_rte_seats_rounds_half_up_not_banker(self):
        # 2 * 0.25 = 0.5 -> round-half-up gives 1 (round() would give 0).
        course = self.env['op.course'].create({
            'name': 'Course G', 'code': 'CG01', 'total_intake': 2,
        })
        self.assertEqual(course.rte_seats, 1)
        self.assertNotEqual(course.rte_seats, round(2 * 0.25))

    def test_negative_total_intake_raises(self):
        with self.assertRaises(ValidationError):
            self.env['op.course'].create({
                'name': 'Course H', 'code': 'CH01', 'total_intake': -5,
            })

    def test_negative_rte_seats_manual_raises(self):
        with self.assertRaises(ValidationError):
            self.env['op.course'].create({
                'name': 'Course I', 'code': 'CI01', 'total_intake': 10,
                'rte_seats_manual': -1,
            })

    def test_rte_seats_zero_intake(self):
        course = self.env['op.course'].create({
            'name': 'Course C', 'code': 'CC01', 'total_intake': 0,
        })
        self.assertEqual(course.rte_seats, 0)

    def test_rte_seats_manual_override(self):
        course = self.env['op.course'].create({
            'name': 'Course D', 'code': 'CD01', 'total_intake': 40,
            'rte_seats_manual': 15,
        })
        self.assertEqual(course.rte_seats, 15)

    def test_rte_seats_recomputes_when_intake_changes(self):
        course = self.env['op.course'].create({
            'name': 'Course E', 'code': 'CE01', 'total_intake': 40,
        })
        self.assertEqual(course.rte_seats, 10)
        course.total_intake = 80
        self.assertEqual(course.rte_seats, 20)

    def test_rte_seats_manual_override_takes_priority_after_change(self):
        course = self.env['op.course'].create({
            'name': 'Course F', 'code': 'CF01', 'total_intake': 40,
        })
        self.assertEqual(course.rte_seats, 10)
        course.rte_seats_manual = 3
        self.assertEqual(course.rte_seats, 3)
        # Clearing the manual override falls back to the computed value.
        course.rte_seats_manual = 0
        self.assertEqual(course.rte_seats, 10)
