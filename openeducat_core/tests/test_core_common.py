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


from odoo.tests import TransactionCase


class TestCoreCommon(TransactionCase):
    def setUp(self):
        super(TestCoreCommon, self).setUp()
        self.op_batch = self.env['op.batch']
        self.op_faculty = self.env['op.faculty']
        self.op_course = self.env['op.course']
        self.res_company = self.env['res.users']
        self.op_student = self.env['op.student']
        self.hr_emp = self.env['hr.employee']
        self.subject_registration = self.env['op.subject.registration']
        self.op_update = self.env['publisher_warranty.contract']
        self.employ_wizard = self.env['wizard.op.faculty.employee']
        self.faculty_user_wizard = self.env['wizard.op.faculty']
        self.studnet_wizard = self.env['wizard.op.student']

        # These tests used to reference openeducat_core demo data (op_student_1,
        # op_faculty_1, op_course_1, op_batch_1, op_res_partner_14/30) directly, but
        # demo data is not guaranteed to be loaded, so build fixtures here instead.
        self.partner_for_faculty = self.env['res.partner'].create({
            'name': 'Core Faculty Partner Fixture', 'email': 'core.faculty.partner@example.com',
        })
        self.partner_for_student = self.env['res.partner'].create({
            'name': 'Core Student Partner Fixture', 'email': 'core.student.partner@example.com',
        })
        self.course_1 = self.op_course.create({'name': 'Core Course 1', 'code': 'CORE-C1'})
        self.batch_1 = self.op_batch.create({
            'name': 'Core Batch 1', 'code': 'CORE-B1', 'course_id': self.course_1.id,
            'start_date': '2026-01-01', 'end_date': '2026-12-31',
        })
        self.faculty_1 = self.op_faculty.create({
            'first_name': 'Core', 'last_name': 'Faculty One',
            'birth_date': '1985-01-01', 'gender': 'male',
        })
        self.student_1 = self.op_student.create({
            'first_name': 'Core', 'last_name': 'Student One',
            'gr_no': 'CORE-S1', 'gender': 'm', 'email': 'core.student.one@example.com',
        })
        self.env['op.student.course'].create({
            'student_id': self.student_1.id, 'course_id': self.course_1.id,
            'batch_id': self.batch_1.id, 'state': 'running',
        })
