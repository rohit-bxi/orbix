# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Sanity checks for the ir.rule set shipped in security/student_portal_security.xml:
a portal user (student or parent) may only read rows tied to themself or to
one of their res.users.child_ids - never another family's data."""
from odoo import fields
from odoo.tests.common import tagged

from .common import TestStudentPortalCommon


@tagged('post_install', '-at_install')
class TestStudentPortalAccess(TestStudentPortalCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student_a = cls._make_student()
        cls.student_b = cls._make_student()
        cls.parent_user = cls._make_portal_user('parent')
        cls.parent_user.child_ids = [(6, 0, [cls.student_a.user_id.id])]

    def test_student_sees_only_own_attendance(self):
        line_a = self._make_attendance(self.student_a, [True])[0]
        line_b = self._make_attendance(self.student_b, [True])[0]

        visible = self.env['op.attendance.line'].with_user(self.student_a.user_id).search([])
        self.assertIn(line_a, visible)
        self.assertNotIn(line_b, visible)

    def test_parent_sees_child_attendance_not_unrelated_student(self):
        line_a = self._make_attendance(self.student_a, [True])[0]
        line_b = self._make_attendance(self.student_b, [True])[0]

        visible = self.env['op.attendance.line'].with_user(self.parent_user).search([])
        self.assertIn(line_a, visible)
        self.assertNotIn(line_b, visible)

    def test_student_cannot_read_unrelated_attendance_directly(self):
        line_b = self._make_attendance(self.student_b, [True])[0]
        line_b.invalidate_recordset()
        LineAsStudentA = self.env['op.attendance.line'].with_user(self.student_a.user_id)
        with self.assertRaises(Exception):
            LineAsStudentA.browse(line_b.id).present

    def test_student_sees_only_own_session(self):
        session_a = self._make_session(self.student_a, fields.Datetime.now())
        session_b = self._make_session(self.student_b, fields.Datetime.now())

        visible = self.env['op.session'].with_user(self.student_a.user_id).search([])
        self.assertIn(session_a, visible)
        self.assertNotIn(session_b, visible)

    def test_student_sees_only_own_marksheet_line(self):
        marksheet_a = self._make_marksheet(self.student_a, 80)
        marksheet_b = self._make_marksheet(self.student_b, 90)

        visible = self.env['op.marksheet.line'].with_user(self.student_a.user_id).search([])
        self.assertIn(marksheet_a, visible)
        self.assertNotIn(marksheet_b, visible)

    def test_student_sees_only_own_result_line(self):
        self._make_marksheet(self.student_a, 80)
        self._make_marksheet(self.student_b, 90)

        visible_students = self.env['op.result.line'].with_user(self.student_a.user_id).search([]).student_id
        self.assertIn(self.student_a, visible_students)
        self.assertNotIn(self.student_b, visible_students)

    def test_student_sees_only_own_media_movement(self):
        movement_a = self._make_library_movement(self.student_a)
        movement_b = self._make_library_movement(self.student_b)

        visible = self.env['op.media.movement'].with_user(self.student_a.user_id).search([])
        self.assertIn(movement_a, visible)
        self.assertNotIn(movement_b, visible)

    def test_student_sees_only_own_fees_details(self):
        fee_a = self._make_fee_invoice(self.student_a, 500.0)
        fee_b = self._make_fee_invoice(self.student_b, 500.0)

        visible = self.env['op.student.fees.details'].with_user(self.student_a.user_id).search([])
        self.assertIn(fee_a, visible)
        self.assertNotIn(fee_b, visible)

    def test_student_cannot_read_unrelated_fees_details_directly(self):
        fee_b = self._make_fee_invoice(self.student_b, 500.0)
        fee_b.invalidate_recordset()
        FeeAsStudentA = self.env['op.student.fees.details'].with_user(self.student_a.user_id)
        with self.assertRaises(Exception):
            FeeAsStudentA.browse(fee_b.id).amount

    def test_student_sees_only_own_allocated_assignment(self):
        assignment_a = self._make_assignment(self.student_a)
        assignment_b = self._make_assignment(self.student_b)

        visible = self.env['op.assignment'].with_user(self.student_a.user_id).search([])
        self.assertIn(assignment_a, visible)
        self.assertNotIn(assignment_b, visible)

    def test_student_sees_only_own_assignment_submission(self):
        assignment_a = self._make_assignment(self.student_a)
        assignment_b = self._make_assignment(self.student_b)
        sub_a = self._make_assignment_submission(assignment_a, self.student_a)
        sub_b = self._make_assignment_submission(assignment_b, self.student_b)

        visible = self.env['op.assignment.sub.line'].with_user(self.student_a.user_id).search([])
        self.assertIn(sub_a, visible)
        self.assertNotIn(sub_b, visible)
