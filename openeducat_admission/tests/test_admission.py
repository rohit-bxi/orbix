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

import logging

from odoo.tests import tagged

from .test_admission_common import TestAdmissionCommon


# TestAdmissionCommon.setUp creates op.course records. Other installed modules (e.g.
# bxi_rte_admission) add required fields with defaults to op.course via model
# inheritance; running at_install (the default) can execute before those patches are
# applied depending on module load order, so these need the full registry from
# post_install (same species of bug as the res.company/payment.provider timing issue
# fixed earlier in helpdesk's tests).
@tagged('post_install', '-at_install')
class TestAdmission(TestAdmissionCommon):

    def setUp(self):
        super(TestAdmission, self).setUp()

    def test_case_1_admissions(self):
        self.op_admission._onchange_name()

        vals = {
            'name': 'AHIR',
            'first_name': 'Nikul',
            'middle_name': 'M',
            'last_name': 'Last',
            'application_number': self.env.ref(
                'openeducat_admission.seq_op_admission').id,
            'birth_date': '2002-12-20',
            'course_id': self.course_5.id,
            'batch_id': self.batch_4.id,
            'phone': 32234234,
            'mobile': 93432,
            'email': 'nik.ahir@gmail.com',
            'state': 'submit',
            'gender': 'm',
            'register_id': self.admission_register_3.id,
            'image': False
        }

        studnet_1 = self.op_admission.create(vals)
        studnet_1.enroll_student()

        vals_2 = {
            'name': 'Ahir',
            'first_name': 'Nikul',
            'middle_name': 'M',
            'last_name': 'Last',
            'birth_date': '2002-12-20',
            'course_id': self.course_5.id,
            'batch_id': self.batch_4.id,
            'phone': 32234234,
            'mobile': 93432,
            'email': 'nisak.ahir@gmail.com',
            'state': 'submit',
            'gender': 'm',
            'register_id': self.admission_register_3.id,
            'student_id': self.student_18.id,
            'fees_term_id': self.fees_term.id,
            'fees': 1000,
        }

        studnet_2 = self.op_admission.create(vals_2)
        studnet_2.enroll_student()
        studnet_2.onchange_student()

        # Exercise the workflow/onchange methods on the records this test created,
        # not on every op.admission that happens to exist in the database (searching
        # unconditionally would run state-transition methods against real, unrelated
        # data and can fail on legacy rows that don't satisfy constraints added later).
        admissions = studnet_1 | studnet_2
        for admission in admissions:
            admission._onchange_name()
            admission.onchange_register()
            admission.onchange_course()
            admission._check_admission_register()
            admission._check_birthdate()
            admission.submit_form()
            admission.admission_confirm()
            admission.confirm_in_progress()
            # Not calling get_student_vals() here: enroll_student() above already
            # invokes it for any admission without a student_id yet (studnet_1), and
            # calling it again would create a second res.users with the same login/
            # email, which is rejected by the "unique login" constraint.
            admission.confirm_rejected()
            admission.confirm_pending()
            admission.confirm_cancel()
            admission.confirm_to_draft()
            admission.open_student()


@tagged('post_install', '-at_install')
class TestAdmissionregister(TestAdmissionCommon):

    def setUp(self):
        super(TestAdmissionregister, self).setUp()

    def test_case_1_register(self):
        register = self.op_register.search([])

        for registers in register:
            logging.info('Admission registar Name : %s :' % (registers.name))

        register.confirm_register()
        register.set_to_draft()
        register.cancel_register()
        register.start_application()
        register.start_admission()
        register.close_register()
        register.check_dates()
        register.check_no_of_admission()


@tagged('post_install', '-at_install')
class TestAdmissionAnalysisWizard(TestAdmissionCommon):

    def setUp(self):
        super(TestAdmissionAnalysisWizard, self).setUp()

    def test_wizard_admission_analysis(self):
        vals = {
            'course_id': self.course_2.id,
            'start_date': '2018-01-01',
            'end_date': '2019-12-30',
        }
        admission = self.wizard_admission.create(vals)
        admission.print_report()


@tagged('post_install', '-at_install')
class TestAdmissionScenarios(TestAdmissionCommon):

    def setUp(self):
        super(TestAdmissionScenarios, self).setUp()

    def test_01_admission_workflow(self):
        """ Test the complete admission state transition workflow """
        from odoo.exceptions import ValidationError
        
        course = self.course_1
        
        register = self.op_register.create({
            'name': 'Test Register 2026',
            'course_id': course.id,
            'start_date': '2026-01-01',
            'end_date': '2026-12-31',
            'min_count': 1,
            'max_count': 50,
        })
        register.confirm_register()
        register.start_application()
        self.assertEqual(register.state, 'application')

        admission = self.op_admission.create({
            'name': 'DOE',
            'first_name': 'John',
            'last_name': 'Doe',
            'birth_date': '2005-01-01',
            'gender': 'm',
            'course_id': course.id,
            'register_id': register.id,
            'email': 'john.doe@example.com',
            'state': 'draft',
        })
        self.assertEqual(admission.state, 'draft')

        admission.submit_form()
        self.assertEqual(admission.state, 'submit')
        
        admission.confirm_in_progress()
        self.assertEqual(admission.state, 'confirm')
        
        admission.admission_confirm()
        self.assertEqual(admission.state, 'admission')

        admission.enroll_student()
        self.assertEqual(admission.state, 'done')
        
        self.assertTrue(admission.student_id)
        self.assertEqual(admission.student_id.first_name, 'John')

    def test_02_register_capacity(self):
        """ Test admission capacity constraints on the register """
        from odoo.exceptions import ValidationError
        
        course = self.course_2
        register = self.op_register.create({
            'name': 'Test Registration Full',
            'course_id': course.id,
            'start_date': '2026-01-01',
            'end_date': '2026-12-31',
            'min_count': 1,
            'max_count': 1,
        })
        register.confirm_register()
        register.start_application()

        admission1 = self.op_admission.create({
            'name': 'A',
            'first_name': 'Test',
            'last_name': '1',
            'birth_date': '2005-01-01',
            'gender': 'm',
            'course_id': course.id,
            'register_id': register.id,
            'email': 't1@example.com',
        })
        admission1.submit_form()
        admission1.enroll_student()

        admission2 = self.op_admission.create({
            'name': 'B',
            'first_name': 'Test',
            'last_name': '2',
            'birth_date': '2005-01-01',
            'gender': 'm',
            'course_id': course.id,
            'register_id': register.id,
            'email': 't2@example.com',
        })
        
        # Test if an error is raised during over-enrolling
        with self.assertRaises(ValidationError):
            admission2.submit_form()
            admission2.enroll_student()

    def test_03_register_invalid_dates(self):
        """ Test validation when start_date is > end_date """
        from odoo.exceptions import ValidationError
        course = self.course_3
        
        with self.assertRaises(ValidationError):
            self.op_register.create({
                'name': 'Test Invalid Dates',
                'course_id': course.id,
                'start_date': '2026-12-31',
                'end_date': '2026-01-01',
                'min_count': 1,
                'max_count': 50,
            })
