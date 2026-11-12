# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPeopleManagement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({'name': 'PM Class', 'code': 'PM-C'})
        cls.batch = cls.env['op.batch'].create({
            'name': 'PM Section', 'code': 'PM-B', 'course_id': cls.course.id,
            'start_date': '2026-01-01', 'end_date': '2027-12-31',
        })
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Pat', 'last_name': 'Teacher', 'gender': 'male', 'birth_date': '1985-01-01',
        })

    def test_defaults(self):
        self.assertEqual(self.faculty.employment_status, 'active')
        self.assertFalse(self.faculty.timetable_auto_assign)
        self.assertEqual(self.faculty.remaining_weekly_periods, self.faculty.max_weekly_periods)

    def test_remaining_periods_never_negative(self):
        self.faculty.max_weekly_periods = 0
        self.assertEqual(self.faculty.remaining_weekly_periods, 0)
        with self.assertRaises(ValidationError):
            self.faculty.max_weekly_periods = -1

    def test_section_needs_its_class(self):
        with self.assertRaises(ValidationError):
            self.faculty.assigned_batch_ids = self.batch
        self.faculty.write({'assigned_course_ids': [(6, 0, self.course.ids)],
                            'assigned_batch_ids': [(6, 0, self.batch.ids)]})
        self.assertEqual(self.faculty.assigned_batch_ids, self.batch)

    def test_permissions_default_on(self):
        for field in ('can_create_lesson_plans', 'can_assign_homework', 'can_evaluate_assignments',
                      'can_enter_exam_marks', 'can_access_reports'):
            self.assertTrue(self.faculty[field], field)

    def test_designation_follows_to_employee(self):
        job = self.env['hr.job'].create({'name': 'PM Head Teacher'})
        self.faculty.designation_id = job
        self.faculty.create_employee()
        self.faculty.designation_id = job  # re-sync once the employee exists
        self.assertEqual(self.faculty.emp_id.job_id, job)
        other = self.env['hr.job'].create({'name': 'PM Vice Principal'})
        self.faculty.designation_id = other
        self.assertEqual(self.faculty.emp_id.job_id, other)

    def test_document_file_info(self):
        document = self.env['bxi.faculty.document'].create({
            'faculty_id': self.faculty.id, 'doc_type': 'cv', 'name': 'CV',
            'file': base64.b64encode(b'%PDF-1.4\n%%EOF\n'), 'filename': 'cv.pdf'})
        self.assertEqual(document.mimetype, 'application/pdf')
        self.assertEqual(document.file_size, 15)
        self.assertEqual(self.faculty.document_count, 1)
