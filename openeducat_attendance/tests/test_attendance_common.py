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
from odoo.tests import common, tagged


# Creating an op.course triggers rte_gender_restriction (a required field with a
# default that bxi_rte_admission adds to op.course via model inheritance); running
# at_install (the default) can execute before that patch is applied depending on
# module load order, so this needs the full registry from post_install (same fix
# used for the same reason elsewhere in this session, e.g. openeducat_admission).
@tagged('post_install', '-at_install')
class TestAttendanceCommon(common.TransactionCase):
    def setUp(self):
        super(TestAttendanceCommon, self).setUp()
        self.op_attendance_register = self.env['op.attendance.register']
        self.op_attendance_sheet = self.env['op.attendance.sheet']
        self.op_attendance_line = self.env['op.attendance.line']
        self.op_attendance_wizard = self.env['student.attendance']

        # test_attendance.py used to reference openeducat_attendance demo data
        # (op_attendance_register_1) directly, but demo data is not guaranteed to be
        # loaded, so build a fixture here instead.
        self.course = self.env['op.course'].create({'name': 'Attendance Course', 'code': 'ATD-C1'})
        self.batch = self.env['op.batch'].create({
            'name': 'Attendance Batch', 'code': 'ATD-B1', 'course_id': self.course.id,
            'start_date': '2026-01-01', 'end_date': '2026-12-31',
        })
        self.register = self.env['op.attendance.register'].create({
            'name': 'Attendance Register Fixture', 'code': 'ATD-REG1',
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
