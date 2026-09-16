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


from odoo.tests import TransactionCase, tagged


# Creating an op.course triggers rte_gender_restriction (a required field with a
# default that bxi_rte_admission adds to op.course via model inheritance); running
# at_install (the default) can execute before that patch is applied depending on
# module load order, so this needs the full registry from post_install (same fix
# used for the same reason elsewhere in this session, e.g. openeducat_admission).
@tagged('post_install', '-at_install')
class TestAssignmentCommon(TransactionCase):
    def setUp(self):
        super(TestAssignmentCommon, self).setUp()
        self.op_assignment = self.env['op.assignment']
        self.op_assignment_subline = self.env['op.assignment.sub.line']

        # These tests used to reference openeducat_core/openeducat_assignment demo
        # data (op_course_4, op_batch_3, op_subject_10, op_faculty_2, op_student_9,
        # openeducat_assignment.op_assignment_1) directly, but demo data is not
        # guaranteed to be loaded, so build fixtures here instead.
        self.assignment_type = self.env['grading.assignment.type'].create({
            'name': 'Assignment Type Fixture', 'code': 'ASG-TYPE1',
        })
        self.course = self.env['op.course'].create({'name': 'Assignment Course', 'code': 'ASG-C1'})
        self.batch = self.env['op.batch'].create({
            'name': 'Assignment Batch', 'code': 'ASG-B1', 'course_id': self.course.id,
            'start_date': '2026-01-01', 'end_date': '2026-12-31',
        })
        self.subject = self.env['op.subject'].create({'name': 'Assignment Subject', 'code': 'ASG-S1'})
        self.faculty = self.env['op.faculty'].create({
            'first_name': 'Assignment', 'last_name': 'Faculty',
            'birth_date': '1985-01-01', 'gender': 'male',
        })
        self.student = self.env['op.student'].create({
            'first_name': 'Assignment', 'last_name': 'Student',
            'gr_no': 'ASG-S001', 'gender': 'm',
        })
