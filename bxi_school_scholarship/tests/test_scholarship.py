from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStudentScholarship(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({
            'name': 'Scholarship Course', 'code': 'SCH-C1',
        })
        cls.batch = cls.env['op.batch'].create({
            'name': 'Scholarship Batch', 'code': 'SCH-B1',
            'course_id': cls.course.id,
            'start_date': '2026-01-01', 'end_date': '2026-12-31',
        })
        cls.student = cls.env['op.student'].create({
            'first_name': 'Scholar', 'last_name': 'Student',
            'gr_no': 'SCH-001', 'gender': 'f',
        })
        cls.env['op.student.course'].create({
            'student_id': cls.student.id,
            'course_id': cls.course.id,
            'batch_id': cls.batch.id,
            'state': 'running',
        })
        cls.academic_year = cls.env['op.academic.year'].create({
            'name': 'AY Scholarship Test',
            'start_date': '2026-01-01',
            'end_date': '2026-12-31',
        })
        cls.program = cls.env['bxi.scholarship.program'].create({
            'name': 'Merit Program',
            'scholarship_type': 'merit',
            'default_coverage_type': 'percentage',
            'default_coverage_percentage': 25.0,
        })
        cls.fee_category_1 = cls.env['product.product'].create({
            'name': 'Tuition Fee', 'lst_price': 1000.0,
        })
        cls.fee_category_2 = cls.env['product.product'].create({
            'name': 'Lab Fee', 'lst_price': 200.0,
        })

    def _make_scholarship(self, **kwargs):
        vals = {
            'student_id': self.student.id,
            'scholarship_type': 'merit',
            'academic_year_id': self.academic_year.id,
            'coverage_type': 'percentage',
            'coverage_percentage': 20.0,
            'valid_from': '2026-01-01',
            'valid_until': '2026-12-31',
        }
        vals.update(kwargs)
        return self.env['bxi.student.scholarship'].create(vals)

    # -- basic create / sequencing -----------------------------------

    def test_sequence_assigned_on_create(self):
        scholarship = self._make_scholarship()
        self.assertNotEqual(scholarship.name, 'New')
        self.assertTrue(scholarship.name)

    def test_default_approval_status_is_draft(self):
        scholarship = self._make_scholarship()
        self.assertEqual(scholarship.approval_status, 'draft')

    def test_class_and_section_computed_from_running_enrollment(self):
        scholarship = self._make_scholarship()
        self.assertEqual(scholarship.class_id, self.course)
        self.assertEqual(scholarship.section_id, self.batch)

    # -- coverage value constraints ------------------------------------

    def test_percentage_coverage_over_100_raises(self):
        with self.assertRaises(ValidationError):
            self._make_scholarship(coverage_type='percentage', coverage_percentage=150.0)

    def test_percentage_coverage_negative_raises(self):
        with self.assertRaises(ValidationError):
            self._make_scholarship(coverage_type='percentage', coverage_percentage=-5.0)

    def test_fixed_amount_negative_raises(self):
        with self.assertRaises(ValidationError):
            self._make_scholarship(coverage_type='fixed_amount', fixed_amount=-100.0)

    def test_max_amount_limit_negative_raises(self):
        with self.assertRaises(ValidationError):
            self._make_scholarship(max_amount_limit=-50.0)

    def test_valid_percentage_and_fixed_amount_do_not_raise(self):
        scholarship = self._make_scholarship(coverage_type='percentage', coverage_percentage=50.0)
        self.assertEqual(scholarship.coverage_percentage, 50.0)

    # -- onchange from program ------------------------------------------

    def test_onchange_program_id_applies_defaults(self):
        scholarship = self.env['bxi.student.scholarship'].new({
            'student_id': self.student.id,
            'academic_year_id': self.academic_year.id,
        })
        scholarship.program_id = self.program
        scholarship._onchange_program_id()
        self.assertEqual(scholarship.scholarship_type, 'merit')
        self.assertEqual(scholarship.coverage_type, 'percentage')
        self.assertEqual(scholarship.coverage_percentage, 25.0)

    # -- fee line discount computation -----------------------------------

    def test_percentage_discount_computed_per_line(self):
        scholarship = self._make_scholarship(coverage_type='percentage', coverage_percentage=20.0)
        line = self.env['bxi.student.scholarship.fee.line'].create({
            'scholarship_id': scholarship.id,
            'fee_category_id': self.fee_category_1.id,
            'total_amount': 1000.0,
        })
        self.assertEqual(line.discount_amount, 200.0)
        self.assertEqual(line.net_amount, 800.0)
        self.assertEqual(scholarship.total_fee_amount, 1000.0)
        self.assertEqual(scholarship.scholarship_amount, 200.0)
        self.assertEqual(scholarship.net_payable_amount, 800.0)

    def test_fixed_amount_discount_split_across_in_scope_lines(self):
        scholarship = self._make_scholarship(coverage_type='fixed_amount', fixed_amount=300.0)
        line_1 = self.env['bxi.student.scholarship.fee.line'].create({
            'scholarship_id': scholarship.id,
            'fee_category_id': self.fee_category_1.id,
            'total_amount': 1000.0,
        })
        line_2 = self.env['bxi.student.scholarship.fee.line'].create({
            'scholarship_id': scholarship.id,
            'fee_category_id': self.fee_category_2.id,
            'total_amount': 200.0,
        })
        # 300 fixed amount split evenly across the two in-scope lines: 150 each.
        self.assertEqual(line_1.discount_amount, 150.0)
        self.assertEqual(line_2.discount_amount, 150.0)

    def test_discount_clamped_to_line_total(self):
        scholarship = self._make_scholarship(coverage_type='percentage', coverage_percentage=100.0)
        line = self.env['bxi.student.scholarship.fee.line'].create({
            'scholarship_id': scholarship.id,
            'fee_category_id': self.fee_category_1.id,
            'total_amount': 1000.0,
        })
        self.assertEqual(line.discount_amount, 1000.0)
        self.assertEqual(line.net_amount, 0.0)

    def test_max_amount_limit_caps_header_scholarship_amount(self):
        scholarship = self._make_scholarship(
            coverage_type='percentage', coverage_percentage=50.0, max_amount_limit=100.0)
        self.env['bxi.student.scholarship.fee.line'].create({
            'scholarship_id': scholarship.id,
            'fee_category_id': self.fee_category_1.id,
            'total_amount': 1000.0,
        })
        # Line-level discount (500) is uncapped, but the header total is capped at 100.
        self.assertEqual(scholarship.scholarship_amount, 100.0)
        self.assertEqual(scholarship.net_payable_amount, 900.0)

    def test_specific_fee_category_scope_excludes_out_of_scope_lines(self):
        scholarship = self._make_scholarship(
            coverage_type='percentage', coverage_percentage=20.0,
            fee_category_scope='specific',
            applicable_fee_category_ids=[(6, 0, [self.fee_category_1.id])],
        )
        in_scope_line = self.env['bxi.student.scholarship.fee.line'].create({
            'scholarship_id': scholarship.id,
            'fee_category_id': self.fee_category_1.id,
            'total_amount': 1000.0,
        })
        out_of_scope_line = self.env['bxi.student.scholarship.fee.line'].create({
            'scholarship_id': scholarship.id,
            'fee_category_id': self.fee_category_2.id,
            'total_amount': 200.0,
        })
        self.assertEqual(in_scope_line.discount_amount, 200.0)
        self.assertEqual(out_of_scope_line.discount_amount, 0.0)

    def test_duplicate_fee_category_on_same_scholarship_raises(self):
        scholarship = self._make_scholarship()
        self.env['bxi.student.scholarship.fee.line'].create({
            'scholarship_id': scholarship.id,
            'fee_category_id': self.fee_category_1.id,
            'total_amount': 1000.0,
        })
        with self.assertRaises(ValidationError):
            self.env['bxi.student.scholarship.fee.line'].create({
                'scholarship_id': scholarship.id,
                'fee_category_id': self.fee_category_1.id,
                'total_amount': 500.0,
            })

    # -- approval workflow -------------------------------------------------

    def test_approval_workflow_full_cycle(self):
        scholarship = self._make_scholarship()
        scholarship.action_submit()
        self.assertEqual(scholarship.approval_status, 'pending')
        scholarship.action_approve()
        self.assertEqual(scholarship.approval_status, 'approved')
        self.assertEqual(scholarship.approved_by, self.env.user)
        self.assertTrue(scholarship.approval_date)

    def test_reject_sets_status(self):
        scholarship = self._make_scholarship()
        scholarship.action_submit()
        scholarship.action_reject()
        self.assertEqual(scholarship.approval_status, 'rejected')

    def test_reset_to_draft_clears_approval_fields(self):
        scholarship = self._make_scholarship()
        scholarship.action_submit()
        scholarship.action_approve()
        scholarship.action_reset_to_draft()
        self.assertEqual(scholarship.approval_status, 'draft')
        self.assertFalse(scholarship.approved_by)
        self.assertFalse(scholarship.approval_date)

    # -- student smart button ------------------------------------------

    def test_student_scholarship_count_and_smart_button(self):
        self.assertEqual(self.student.scholarship_count, 0)
        self._make_scholarship()
        self.assertEqual(self.student.scholarship_count, 1)
        action = self.student.action_view_scholarships()
        self.assertEqual(action['res_model'], 'bxi.student.scholarship')
        self.assertEqual(action['domain'], [('student_id', '=', self.student.id)])


@tagged('post_install', '-at_install')
class TestScholarshipRemoveWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student = cls.env['op.student'].create({
            'first_name': 'Remove', 'last_name': 'Student',
            'gr_no': 'SCH-REM-001', 'gender': 'm',
        })
        cls.academic_year = cls.env['op.academic.year'].create({
            'name': 'AY Remove Test',
            'start_date': '2026-01-01',
            'end_date': '2026-12-31',
        })
        cls.fee_category = cls.env['product.product'].create({
            'name': 'Tuition Fee Remove', 'lst_price': 1000.0,
        })
        cls.scholarship = cls.env['bxi.student.scholarship'].create({
            'student_id': cls.student.id,
            'scholarship_type': 'merit',
            'academic_year_id': cls.academic_year.id,
            'coverage_type': 'percentage',
            'coverage_percentage': 20.0,
            'valid_from': '2026-01-01',
            'valid_until': '2026-12-31',
        })
        cls.env['bxi.student.scholarship.fee.line'].create({
            'scholarship_id': cls.scholarship.id,
            'fee_category_id': cls.fee_category.id,
            'total_amount': 1000.0,
        })

    def test_wizard_computes_financial_impact(self):
        wizard = self.env['bxi.scholarship.remove.wizard'].create({
            'scholarship_id': self.scholarship.id,
        })
        self.assertEqual(wizard.lost_scholarship_amount, self.scholarship.scholarship_amount)
        self.assertEqual(wizard.current_pending_amount, self.scholarship.net_payable_amount)
        self.assertEqual(wizard.new_pending_amount, self.scholarship.total_fee_amount)

    def test_confirm_remove_without_correct_text_raises(self):
        wizard = self.env['bxi.scholarship.remove.wizard'].create({
            'scholarship_id': self.scholarship.id,
            'confirmation_text': 'wrong',
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm_remove()
        self.assertTrue(self.scholarship.active)

    def test_confirm_remove_with_correct_text_archives_scholarship(self):
        wizard = self.env['bxi.scholarship.remove.wizard'].create({
            'scholarship_id': self.scholarship.id,
            'confirmation_text': 'remove',
        })
        result = wizard.action_confirm_remove()
        self.assertFalse(self.scholarship.active)
        self.assertEqual(result, {'type': 'ir.actions.act_window_close'})
