from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLessonPlan(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({'name': 'Class 8', 'code': 'C8'})
        cls.subject = cls.env['op.subject'].create({'name': 'Science', 'code': 'SCI'})
        cls.teacher = cls.env['op.faculty'].create({
            'first_name': 'Nisha', 'last_name': 'Verma',
            'birth_date': '1987-04-04', 'gender': 'female',
        })
        cls.academic_year = cls.env['op.academic.year'].create({
            'name': 'AY Lesson Plan Test', 'start_date': '2026-06-01', 'end_date': '2027-04-30',
        })
        cls.quarter = cls.env['op.academic.term'].create({
            'name': 'Quarter 1', 'term_start_date': '2026-06-01', 'term_end_date': '2026-08-31',
            'academic_year_id': cls.academic_year.id,
        })

    def _make_plan(self, **overrides):
        vals = {
            'teacher_id': self.teacher.id,
            'subject_id': self.subject.id,
            'class_id': self.course.id,
            'quarter_id': self.quarter.id,
            'topic': 'Photosynthesis',
            'objective': 'Understand the process of photosynthesis',
            'activities': 'Group discussion and diagram labeling',
            'resources': 'Textbook chapter 5, charts',
            'assessment_method': 'Oral quiz',
            'start_date': '2026-06-05',
            'end_date': '2026-06-07',
            'plan_date': '2026-06-05',
        }
        vals.update(overrides)
        return self.env['bxi.lesson.plan'].create(vals)

    # --- compute fields ---

    def test_duration_computed_inclusive(self):
        plan = self._make_plan(start_date='2026-06-05', end_date='2026-06-07')
        self.assertEqual(plan.duration, 3)

    def test_duration_single_day(self):
        plan = self._make_plan(start_date='2026-06-05', end_date='2026-06-05')
        self.assertEqual(plan.duration, 1)

    def test_plan_day_computed(self):
        # 2026-06-05 is a Friday.
        plan = self._make_plan(plan_date='2026-06-05')
        self.assertEqual(plan.plan_day, 'Friday')

    def test_plan_day_recomputes_on_change(self):
        plan = self._make_plan(plan_date='2026-06-05')
        self.assertEqual(plan.plan_day, 'Friday')
        plan.plan_date = '2026-06-06'
        self.assertEqual(plan.plan_day, 'Saturday')

    # --- constraints ---

    def test_end_date_before_start_date_raises(self):
        with self.assertRaises(ValidationError):
            self._make_plan(start_date='2026-06-10', end_date='2026-06-01')

    def test_end_date_equal_start_date_allowed(self):
        plan = self._make_plan(start_date='2026-06-05', end_date='2026-06-05')
        self.assertTrue(plan.id)

    # --- default state and workflow ---

    def test_default_state_pending(self):
        plan = self._make_plan()
        self.assertEqual(plan.state, 'pending')

    def test_action_resubmit_resets_state_and_posts_message(self):
        plan = self._make_plan()
        plan.state = 'rejected'
        message_count_before = len(plan.message_ids)
        plan.action_resubmit()
        self.assertEqual(plan.state, 'pending')
        self.assertGreater(len(plan.message_ids), message_count_before)

    def test_default_teacher_from_current_user(self):
        teacher_for_user = self.env['op.faculty'].create({
            'first_name': 'Self', 'last_name': 'Teacher',
            'birth_date': '1990-01-01', 'gender': 'male',
            'user_id': self.env.uid,
        })
        plan = self.env['bxi.lesson.plan'].create({
            'subject_id': self.subject.id,
            'class_id': self.course.id,
            'quarter_id': self.quarter.id,
            'topic': 'Auto Teacher Topic',
            'objective': 'Objective',
            'activities': 'Activities',
            'resources': 'Resources',
            'assessment_method': 'Assessment',
            'start_date': '2026-06-05',
            'end_date': '2026-06-05',
            'plan_date': '2026-06-05',
        })
        self.assertEqual(plan.teacher_id, teacher_for_user)

    # --- lesson plan lines ---

    def test_line_type_filtered_one2many(self):
        plan = self._make_plan()
        self.env['bxi.lesson.plan.line'].create({
            'lesson_plan_id': plan.id, 'line_type': 'recall_question',
            'name': 'What is chlorophyll?',
        })
        self.env['bxi.lesson.plan.line'].create({
            'lesson_plan_id': plan.id, 'line_type': 'home_work',
            'name': 'Draw the process of photosynthesis',
        })
        self.env['bxi.lesson.plan.line'].create({
            'lesson_plan_id': plan.id, 'line_type': 'remark',
            'name': 'Good participation',
        })
        self.assertEqual(len(plan.line_ids), 3)
        self.assertEqual(len(plan.recall_question_ids), 1)
        self.assertEqual(len(plan.home_work_ids), 1)
        self.assertEqual(len(plan.class_work_ids), 0)
        self.assertEqual(len(plan.remark_ids), 1)

    def test_line_cascade_delete_with_plan(self):
        plan = self._make_plan()
        line = self.env['bxi.lesson.plan.line'].create({
            'lesson_plan_id': plan.id, 'line_type': 'teaching_aid',
            'name': 'Projector slides',
        })
        plan.unlink()
        self.assertFalse(line.exists())

    # --- review wizard ---

    def test_review_wizard_approve(self):
        plan = self._make_plan()
        wizard = self.env['bxi.lesson.plan.review.wizard'].create({
            'lesson_plan_id': plan.id, 'decision': 'approved',
            'feedback': 'Well structured plan.',
        })
        result = wizard.action_confirm()
        self.assertEqual(plan.state, 'approved')
        self.assertEqual(result.get('type'), 'ir.actions.act_window_close')

    def test_review_wizard_reject_default_message(self):
        plan = self._make_plan()
        wizard = self.env['bxi.lesson.plan.review.wizard'].create({
            'lesson_plan_id': plan.id, 'decision': 'rejected',
        })
        wizard.action_confirm()
        self.assertEqual(plan.state, 'rejected')
        last_message = plan.message_ids.sorted('id', reverse=True)[0]
        self.assertIn('Revision requested', last_message.body)
