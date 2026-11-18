###############################################################################
#
#    OpenEduCat Inc
#    Copyright (C) 2009-TODAY OpenEduCat Inc(<https://www.openeducat.org>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Lesser General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################

import time
from logging import info

from .test_assignment_common import TestAssignmentCommon


class TestAssignment(TestAssignmentCommon):

    def setUp(self):
        super(TestAssignment, self).setUp()

    def test_case_assignment(self):
        # Builds its own assignment rather than searching for demo data,
        # which a database created without demo records doesn't have.
        assignment = self.op_assignment.create({
            'name': 'Fixture Assignment', 'marks': 20,
            'assignment_type': self.assignment_type.id,
            'issued_date': time.strftime('%Y-%m-01'),
            'submission_date': time.strftime('%Y-%m-28'),
            'course_id': self.course.id, 'batch_id': self.batch.id,
            'subject_id': self.subject.id, 'faculty_id': self.faculty.id,
            'allocation_ids': [(6, 0, self.student.ids)],
            'description': 'Answer briefly.',
        })
        info('      Name : %s' % assignment.name)
        self.assertEqual(assignment.state, 'draft')
        assignment.act_publish()
        self.assertEqual(assignment.state, 'publish')
        assignment.act_finish()
        self.assertEqual(assignment.state, 'finish')
        assignment.act_cancel()
        self.assertEqual(assignment.state, 'cancel')
        assignment.act_set_to_draft()
        self.assertEqual(assignment.state, 'draft')
        # Changing the course clears the section and the allocated students.
        assignment.onchange_course()
        self.assertFalse(assignment.batch_id)
        self.assertFalse(assignment.allocation_ids)


class TestAssignmentSubline(TestAssignmentCommon):

    def setUp(self):
        super(TestAssignmentSubline, self).setUp()

    def test_case_assignment_subline(self):
        assignment_subline = self.op_assignment_subline.search([])
        assignment = self.env["op.assignment"].create({
            'name': "LRTP - 001 - Asg - 009",
            'state': "draft",
            'marks': 50,
            'assignment_type': self.assignment_type.id,
            'issued_date': time.strftime('%Y-%m-01'),
            'course_id': self.course.id,
            'batch_id': self.batch.id,
            'subject_id': self.subject.id,
            'faculty_id': self.faculty.id,
            'submission_date': time.strftime('%Y-%m-01'),
            'allocation_ids': self.student,
            'description': 'Please answer the following questions briefly:'
                           ' - 1. What are the different types of land',
        })
        assignment_subline1 = self.op_assignment_subline.create({
            'assignment_id': assignment.id,
            'state': "draft",
            'student_id': self.student.id,
            'description': 'The answers of the questions are placed here',
        })
        assignment_subline1.unlink()
        for record in assignment_subline:
            info('      Assignment Name : %s' % record.assignment_id.id)
            info('      Student : %s' % record.student_id.id)
            info('      Description : %s' % record.description)
            info('      State : %s' % record.state)
            info('      submission_date : %s' % record.submission_date)
            info('      Marks : %s' % record.marks)
            info('      Note : %s' % record.note)
            info('      User : %s' % record.user_id.id)
            info('      Faculty : %s' % record.faculty_user_id.id)
            info('      Check User Boolean : %s' % record.user_boolean)
            record.act_draft()
            record.act_submit()
            record.act_accept()
            record.act_change_req()
            record.act_reject()
