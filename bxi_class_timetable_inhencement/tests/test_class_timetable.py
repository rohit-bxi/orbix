from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestClassTimetable(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({'name': 'Class 10', 'code': 'C10'})
        cls.course_2 = cls.env['op.course'].create({'name': 'Class 9', 'code': 'C9'})
        cls.subject = cls.env['op.subject'].create({'name': 'Physics', 'code': 'PHY'})
        cls.teacher = cls.env['op.faculty'].create({
            'first_name': 'Ravi', 'last_name': 'Shah',
            'birth_date': '1982-02-02', 'gender': 'male',
        })
        cls.teacher_2 = cls.env['op.faculty'].create({
            'first_name': 'Meena', 'last_name': 'Iyer',
            'birth_date': '1988-03-03', 'gender': 'female',
        })
        cls.batch = cls.env['op.batch'].create({
            'course_id': cls.course.id, 'name': 'Section A',
        })
        cls.batch_2 = cls.env['op.batch'].create({
            'course_id': cls.course_2.id, 'name': 'Section B',
        })

    def _make_timing(self, name, hour, minute, am_pm, duration=1.0, is_break=False):
        return self.env['op.timing'].create({
            'name': name, 'hour': hour, 'minute': minute,
            'am_pm': am_pm, 'duration': duration, 'is_break': is_break,
        })

    # --- op.batch: batch_class_manager ---

    def test_batch_code_auto_generated(self):
        self.assertEqual(self.batch.code, 'C10-SECTION-A')

    def test_batch_code_suffix_on_duplicate_name(self):
        batch = self.env['op.batch'].create({
            'course_id': self.course.id, 'name': 'Section A',
        })
        self.assertEqual(batch.code, 'C10-SECTION-A-2')

    def test_batch_default_dates_from_academic_year(self):
        academic_year = self.env['op.academic.year'].create({
            'name': 'AY 2026-27', 'start_date': '2026-06-01', 'end_date': '2027-04-30',
        })
        batch = self.env['op.batch'].create({
            'course_id': self.course.id, 'name': 'Section C',
        })
        # academic_year covers "today" so its dates should be used if applicable,
        # otherwise the latest-by-start-date year is used as a fallback.
        self.assertTrue(batch.start_date)
        self.assertTrue(batch.end_date)
        self.assertGreaterEqual(batch.end_date, batch.start_date)

    def test_batch_explicit_dates_kept(self):
        batch = self.env['op.batch'].create({
            'course_id': self.course.id, 'name': 'Section D',
            'start_date': '2026-01-01', 'end_date': '2026-12-31',
        })
        self.assertEqual(str(batch.start_date), '2026-01-01')
        self.assertEqual(str(batch.end_date), '2026-12-31')

    # --- op.faculty: faculty_workload ---

    def test_workload_status_normal(self):
        self.teacher.max_weekly_periods = 30
        self.assertEqual(self.teacher.weekly_period_count, 0)
        self.assertEqual(self.teacher.workload_status, 'normal')

    def test_workload_status_near_and_over_limit(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        self.teacher.max_weekly_periods = 2
        timing_1 = self._make_timing('P1', '9', '00', 'am')
        timing_2 = self._make_timing('P2', '10', '00', 'am')
        self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'monday',
            'timing_id': timing_1.id, 'teacher_id': self.teacher.id,
        })
        self.assertEqual(self.teacher.workload_status, 'near_limit')
        self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'monday',
            'timing_id': timing_2.id, 'teacher_id': self.teacher.id,
        })
        self.assertEqual(self.teacher.weekly_period_count, 2)
        self.assertEqual(self.teacher.workload_status, 'over_limit')

    # --- op.timing ---

    def test_timing_display_label(self):
        timing = self._make_timing('Period 1', '9', '30', 'am', duration=1.0)
        self.assertIn('Period 1', timing.display_label)
        self.assertIn('9:30', timing.display_label)

    def test_timing_break_label(self):
        timing = self._make_timing('Break', '11', '00', 'am', is_break=True)
        self.assertTrue(timing.display_label.startswith('Break'))

    def test_timing_end_before_start_raises(self):
        timing = self._make_timing('P1', '9', '00', 'am')
        with self.assertRaises(ValidationError):
            timing.write({'start_time': 10.0, 'end_time': 9.0})

    # --- bxi.timetable ---

    def test_timetable_unique_course_batch(self):
        self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        with self.assertRaises(Exception):
            self.env['bxi.timetable'].create({
                'course_id': self.course.id, 'batch_id': self.batch.id,
            })

    def test_timetable_display_name(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        self.assertEqual(timetable.display_name, '%s - %s' % (self.course.name, self.batch.name))

    def test_timetable_lock_unlock(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        timetable.action_lock()
        self.assertTrue(timetable.locked)
        timetable.action_unlock()
        self.assertFalse(timetable.locked)

    def test_get_or_create(self):
        timetable = self.env['bxi.timetable']._get_or_create(self.course.id, self.batch.id)
        timetable_again = self.env['bxi.timetable']._get_or_create(self.course.id, self.batch.id)
        self.assertEqual(timetable, timetable_again)

    # --- bxi.timetable.line ---

    def test_timetable_line_unique_slot(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        timing = self._make_timing('P1', '9', '00', 'am')
        self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'monday', 'timing_id': timing.id,
        })
        with self.assertRaises(Exception):
            self.env['bxi.timetable.line'].create({
                'timetable_id': timetable.id, 'day': 'monday', 'timing_id': timing.id,
            })

    def test_timetable_line_blocked_when_locked(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        timing = self._make_timing('P1', '9', '00', 'am')
        timetable.action_lock()
        with self.assertRaises(ValidationError):
            self.env['bxi.timetable.line'].create({
                'timetable_id': timetable.id, 'day': 'monday', 'timing_id': timing.id,
            })

    def test_timetable_line_unlink_blocked_when_locked(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        timing = self._make_timing('P1', '9', '00', 'am')
        line = self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'monday', 'timing_id': timing.id,
        })
        timetable.action_lock()
        with self.assertRaises(ValidationError):
            line.unlink()

    def test_teacher_double_booking_overlap_blocked(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        timing_1 = self._make_timing('P1', '9', '00', 'am', duration=1.0)
        timing_2 = self._make_timing('P2', '9', '30', 'am', duration=1.0)
        self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'monday',
            'timing_id': timing_1.id, 'teacher_id': self.teacher.id,
        })
        with self.assertRaises(ValidationError):
            self.env['bxi.timetable.line'].create({
                'timetable_id': timetable.id, 'day': 'monday',
                'timing_id': timing_2.id, 'teacher_id': self.teacher.id,
            })

    def test_teacher_non_overlapping_periods_allowed(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        timing_1 = self._make_timing('P1', '9', '00', 'am', duration=1.0)
        timing_2 = self._make_timing('P2', '10', '00', 'am', duration=1.0)
        self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'monday',
            'timing_id': timing_1.id, 'teacher_id': self.teacher.id,
        })
        line_2 = self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'monday',
            'timing_id': timing_2.id, 'teacher_id': self.teacher.id,
        })
        self.assertTrue(line_2.id)

    # --- wizards ---

    def test_add_period_wizard_success(self):
        timing = self._make_timing('P1', '9', '00', 'am')
        wizard = self.env['bxi.add.period.wizard'].create({
            'teacher_id': self.teacher.id, 'course_id': self.course.id,
            'batch_id': self.batch.id, 'day': 'tuesday',
            'timing_id': timing.id, 'subject_id': self.subject.id,
        })
        wizard.action_add_period()
        timetable = self.env['bxi.timetable']._get_or_create(self.course.id, self.batch.id)
        self.assertEqual(len(timetable.line_ids), 1)

    def test_add_period_wizard_blocked_when_locked(self):
        timetable = self.env['bxi.timetable']._get_or_create(self.course.id, self.batch.id)
        timetable.action_lock()
        timing = self._make_timing('P1', '9', '00', 'am')
        wizard = self.env['bxi.add.period.wizard'].create({
            'teacher_id': self.teacher.id, 'course_id': self.course.id,
            'batch_id': self.batch.id, 'day': 'tuesday',
            'timing_id': timing.id, 'subject_id': self.subject.id,
        })
        with self.assertRaises(ValidationError):
            wizard.action_add_period()

    def test_add_period_wizard_blocked_over_workload_limit(self):
        self.teacher.max_weekly_periods = 0
        timing = self._make_timing('P1', '9', '00', 'am')
        wizard = self.env['bxi.add.period.wizard'].create({
            'teacher_id': self.teacher.id, 'course_id': self.course.id,
            'batch_id': self.batch.id, 'day': 'tuesday',
            'timing_id': timing.id, 'subject_id': self.subject.id,
        })
        with self.assertRaises(ValidationError):
            wizard.action_add_period()

    def test_remove_period_wizard(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        timing = self._make_timing('P1', '9', '00', 'am')
        line = self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'monday', 'timing_id': timing.id,
        })
        wizard = self.env['bxi.remove.period.wizard'].create({'line_id': line.id})
        self.assertEqual(wizard.class_section, timetable.display_name)
        wizard.action_remove_period()
        self.assertFalse(line.exists())

    def test_transfer_period_wizard_success(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        timing = self._make_timing('P1', '9', '00', 'am')
        line = self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'monday',
            'timing_id': timing.id, 'teacher_id': self.teacher.id,
        })
        wizard = self.env['bxi.transfer.period.wizard'].create({
            'from_teacher_id': self.teacher.id, 'course_id': self.course.id,
            'batch_id': self.batch.id, 'day': 'monday', 'timing_id': timing.id,
            'to_teacher_id': self.teacher_2.id,
        })
        wizard.action_transfer()
        self.assertEqual(line.teacher_id, self.teacher_2)

    def test_transfer_period_wizard_no_match_raises(self):
        timing = self._make_timing('P1', '9', '00', 'am')
        wizard = self.env['bxi.transfer.period.wizard'].create({
            'from_teacher_id': self.teacher.id, 'course_id': self.course.id,
            'batch_id': self.batch.id, 'day': 'monday', 'timing_id': timing.id,
            'to_teacher_id': self.teacher_2.id,
        })
        with self.assertRaises(ValidationError):
            wizard.action_transfer()

    def test_transfer_period_wizard_blocked_over_workload_limit(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        timing = self._make_timing('P1', '9', '00', 'am')
        self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'monday',
            'timing_id': timing.id, 'teacher_id': self.teacher.id,
        })
        self.teacher_2.max_weekly_periods = 0
        wizard = self.env['bxi.transfer.period.wizard'].create({
            'from_teacher_id': self.teacher.id, 'course_id': self.course.id,
            'batch_id': self.batch.id, 'day': 'monday', 'timing_id': timing.id,
            'to_teacher_id': self.teacher_2.id,
        })
        with self.assertRaises(ValidationError):
            wizard.action_transfer()

    def test_reassign_class_wizard_success(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        timing = self._make_timing('P1', '9', '00', 'am')
        line = self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'monday',
            'timing_id': timing.id, 'teacher_id': self.teacher.id,
        })
        wizard = self.env['bxi.reassign.class.wizard'].create({
            'teacher_id': self.teacher.id,
            'current_course_id': self.course.id, 'current_batch_id': self.batch.id,
            'new_course_id': self.course_2.id, 'new_batch_id': self.batch_2.id,
        })
        wizard.action_reassign()
        destination = self.env['bxi.timetable']._get_or_create(self.course_2.id, self.batch_2.id)
        self.assertEqual(line.timetable_id, destination)

    def test_reassign_class_wizard_no_periods_raises(self):
        self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        wizard = self.env['bxi.reassign.class.wizard'].create({
            'teacher_id': self.teacher.id,
            'current_course_id': self.course.id, 'current_batch_id': self.batch.id,
            'new_course_id': self.course_2.id, 'new_batch_id': self.batch_2.id,
        })
        with self.assertRaises(ValidationError):
            wizard.action_reassign()

    def test_reassign_class_wizard_conflict_raises(self):
        timetable = self.env['bxi.timetable'].create({
            'course_id': self.course.id, 'batch_id': self.batch.id,
        })
        timing = self._make_timing('P1', '9', '00', 'am')
        self.env['bxi.timetable.line'].create({
            'timetable_id': timetable.id, 'day': 'monday',
            'timing_id': timing.id, 'teacher_id': self.teacher.id,
        })
        destination = self.env['bxi.timetable'].create({
            'course_id': self.course_2.id, 'batch_id': self.batch_2.id,
        })
        self.env['bxi.timetable.line'].create({
            'timetable_id': destination.id, 'day': 'monday',
            'timing_id': timing.id, 'teacher_id': self.teacher_2.id,
        })
        wizard = self.env['bxi.reassign.class.wizard'].create({
            'teacher_id': self.teacher.id,
            'current_course_id': self.course.id, 'current_batch_id': self.batch.id,
            'new_course_id': self.course_2.id, 'new_batch_id': self.batch_2.id,
        })
        with self.assertRaises(ValidationError):
            wizard.action_reassign()
