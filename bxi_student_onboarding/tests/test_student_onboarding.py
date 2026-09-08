# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestStudentOnboarding(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({
            'name': 'Onboarding Course', 'code': 'OBC',
        })
        cls.batch = cls.env['op.batch'].create({
            'name': 'Batch OB', 'code': 'OBB',
            'course_id': cls.course.id,
            'start_date': '2026-06-01', 'end_date': '2027-05-31',
        })
        cls.relationship = cls.env['op.parent.relationship'].create({
            'name': 'Father',
        })
        cls.other_student = cls.env['op.student'].create({
            'first_name': 'Sibling', 'last_name': 'Roe',
            'gr_no': 'OB-SIB-001', 'gender': 'm',
        })
        cls.parent_partner = cls.env['res.partner'].create({
            'name': 'Robert Roe', 'is_parent': True,
        })
        cls.parent = cls.env['op.parent'].create({
            'name': cls.parent_partner.id,
            'relationship_id': cls.relationship.id,
            'student_ids': [(6, 0, [cls.other_student.id])],
        })

    def _basic_info_vals(self, **overrides):
        vals = {
            'full_name': 'Jane Middle Doe',
            'gender': 'f',
            'birth_date': '2015-05-10',
            'email': 'jane.doe@example.com',
            'phone': '1234567890',
        }
        vals.update(overrides)
        return vals

    def _academic_vals(self, **overrides):
        vals = {
            'course_id': self.course.id,
            'batch_id': self.batch.id,
            'roll_number': '1',
            'enrollment_status': 'new_admission',
        }
        vals.update(overrides)
        return vals

    def test_admission_number_auto_assigned_on_create(self):
        onboarding = self.env['bxi.student.onboarding'].create({})
        self.assertTrue(onboarding.admission_number)
        self.assertNotEqual(onboarding.admission_number, '/')

    def test_next_from_basic_info_requires_fields(self):
        onboarding = self.env['bxi.student.onboarding'].create({})
        with self.assertRaises(ValidationError):
            onboarding.action_next()
        self.assertEqual(onboarding.state, 'basic_info')

    def test_next_from_basic_info_succeeds_when_filled(self):
        onboarding = self.env['bxi.student.onboarding'].create(
            self._basic_info_vals())
        onboarding.action_next()
        self.assertEqual(onboarding.state, 'academic_info')

    def test_next_from_academic_info_requires_fields(self):
        onboarding = self.env['bxi.student.onboarding'].create(
            self._basic_info_vals())
        onboarding.action_next()
        with self.assertRaises(ValidationError):
            onboarding.action_next()
        self.assertEqual(onboarding.state, 'academic_info')

    def test_next_from_academic_info_succeeds_when_filled(self):
        onboarding = self.env['bxi.student.onboarding'].create(
            self._basic_info_vals())
        onboarding.write(self._academic_vals())
        onboarding.action_next()
        self.assertEqual(onboarding.state, 'documents')

    def test_action_back_moves_to_previous_step(self):
        onboarding = self.env['bxi.student.onboarding'].create(
            self._basic_info_vals())
        onboarding.write(self._academic_vals())
        onboarding.action_next()
        self.assertEqual(onboarding.state, 'documents')
        onboarding.action_back()
        self.assertEqual(onboarding.state, 'academic_info')

    def test_onchange_course_clears_batch(self):
        onboarding = self.env['bxi.student.onboarding'].new(
            self._academic_vals())
        onboarding.course_id = self.course.id
        onboarding._onchange_course_id()
        self.assertFalse(onboarding.batch_id)

    def test_complete_onboarding_creates_student(self):
        onboarding = self.env['bxi.student.onboarding'].create(
            self._basic_info_vals(**self._academic_vals()))
        onboarding.action_complete_onboarding()
        self.assertEqual(onboarding.state, 'done')
        self.assertTrue(onboarding.student_id)
        student = onboarding.student_id
        self.assertEqual(student.first_name, 'Jane')
        self.assertEqual(student.last_name, 'Doe')
        self.assertEqual(student.middle_name, 'Middle')
        self.assertEqual(student.gr_no, onboarding.admission_number)
        self.assertEqual(student.enrollment_status, 'new_admission')
        self.assertEqual(student.course_detail_ids.course_id, self.course)
        self.assertEqual(student.course_detail_ids.batch_id, self.batch)

    def test_complete_onboarding_links_existing_parent(self):
        onboarding = self.env['bxi.student.onboarding'].create(
            self._basic_info_vals(**self._academic_vals(),
                                   parent_id=self.parent.id))
        onboarding.action_complete_onboarding()
        self.assertIn(self.parent, onboarding.student_id.parent_ids)

    def test_complete_onboarding_twice_blocked(self):
        onboarding = self.env['bxi.student.onboarding'].create(
            self._basic_info_vals(**self._academic_vals()))
        onboarding.action_complete_onboarding()
        with self.assertRaises(ValidationError):
            onboarding.action_complete_onboarding()

    def test_duplicate_admission_number_blocked(self):
        first = self.env['bxi.student.onboarding'].create(
            self._basic_info_vals())
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['bxi.student.onboarding'].create(
                self._basic_info_vals(admission_number=first.admission_number))
