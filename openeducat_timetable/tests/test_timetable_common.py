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
from odoo.tests import common


class TestTimetableCommon(common.TransactionCase):
    def setUp(self):
        super(TestTimetableCommon, self).setUp()
        self.op_faculty = self.env['op.faculty']
        self.op_session = self.env['op.session']
        self.op_timing = self.env['op.timing']
        self.generate_timetable = self.env['generate.time.table']
        self.wizard_session = self.env['gen.time.table.line']
        self.timetable_report = self.env['time.table.report']

        # Self-contained fixtures — don't rely on demo data being
        # installed (it isn't, in a --test-enable-only run).
        self.course = self.env['op.course'].create({
            'name': 'TT Common Course', 'code': 'TTCC',
        })
        self.subject = self.env['op.subject'].create({
            'name': 'TT Common Subject', 'code': 'TTCS',
        })
        self.course.subject_ids = [(6, 0, [self.subject.id])]
        self.batch = self.env['op.batch'].create({
            'name': 'TT Common Batch', 'code': 'TTCB',
            'course_id': self.course.id,
            'start_date': '2026-06-01', 'end_date': '2027-05-31',
        })
        self.faculty = self.op_faculty.create({
            'first_name': 'TT Common', 'last_name': 'Faculty',
            'gender': 'male', 'birth_date': '1985-01-01',
        })
        self.timing = self.op_timing.create({
            'name': 'TT Common Slot', 'hour': '9', 'minute': '00', 'am_pm': 'am',
        })
