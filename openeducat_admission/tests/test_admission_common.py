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

from datetime import date

from odoo.tests import TransactionCase


class TestAdmissionCommon(TransactionCase):
    def setUp(self):
        super(TestAdmissionCommon, self).setUp()
        self.op_register = self.env['op.admission.register']
        self.op_admission = self.env['op.admission']
        self.wizard_admission = self.env['admission.analysis']
        # These tests used to reference openeducat_core/openeducat_admission demo data
        # (op_course_N, op_batch_4, op_student_18, op_admission_register_3) directly, but
        # demo data is not guaranteed to be loaded, so build fixtures here instead.
        self.course_1 = self.env['op.course'].create({'name': 'Admission Course 1', 'code': 'ADM-C1'})
        self.course_2 = self.env['op.course'].create({'name': 'Admission Course 2', 'code': 'ADM-C2'})
        self.course_3 = self.env['op.course'].create({'name': 'Admission Course 3', 'code': 'ADM-C3'})
        self.course_5 = self.env['op.course'].create({'name': 'Admission Course 5', 'code': 'ADM-C5'})
        self.batch_4 = self.env['op.batch'].create({
            'name': 'Admission Batch 4', 'code': 'ADM-B4', 'course_id': self.course_5.id,
            'start_date': date(2020, 1, 1), 'end_date': date(2030, 12, 31),
        })
        self.student_18 = self.env['op.student'].create({
            'first_name': 'Admission', 'last_name': 'Student 18',
            'gr_no': 'ADM-S18', 'gender': 'm',
        })
        self.admission_register_3 = self.op_register.create({
            'name': 'Admission Register Fixture',
            'course_id': self.course_5.id,
            'start_date': date(2020, 1, 1),
            'end_date': date(2030, 12, 31),
            'min_count': 1,
            'max_count': 50,
        })
        self.fees_term = self.env['op.fees.terms'].create({
            'name': 'Admission Fees Term Fixture',
            'code': 'ADM-FT1',
            'line_ids': [(0, 0, {'due_days': 30, 'value': 100.0})],
        })
