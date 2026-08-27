from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAnnouncement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({
            'name': 'Test Course', 'code': 'ANN-C1',
        })
        cls.other_course = cls.env['op.course'].create({
            'name': 'Other Course', 'code': 'ANN-C2',
        })
        cls.batch = cls.env['op.batch'].create({
            'name': 'Batch A', 'code': 'ANN-B1',
            'course_id': cls.course.id,
            'start_date': '2026-01-01', 'end_date': '2026-12-31',
        })
        cls.student = cls.env['op.student'].create({
            'first_name': 'Ann', 'last_name': 'Student',
            'gr_no': 'ANN-001', 'gender': 'f',
        })
        cls.env['op.student.course'].create({
            'student_id': cls.student.id,
            'course_id': cls.course.id,
            'batch_id': cls.batch.id,
            'state': 'running',
        })
        cls.other_student = cls.env['op.student'].create({
            'first_name': 'Other', 'last_name': 'Student',
            'gr_no': 'ANN-002', 'gender': 'm',
        })
        cls.env['op.student.course'].create({
            'student_id': cls.other_student.id,
            'course_id': cls.other_course.id,
            'state': 'running',
        })

    def _make_announcement(self, **kwargs):
        vals = {
            'title': 'Test Announcement',
            'body': 'This is a test announcement body.',
            'target_audience': 'all_students',
        }
        vals.update(kwargs)
        return self.env['bxi.announcement'].create(vals)

    def test_sequence_assigned_on_create(self):
        announcement = self._make_announcement()
        self.assertNotEqual(announcement.name, 'New')
        self.assertTrue(announcement.name)

    def test_default_state_is_draft(self):
        announcement = self._make_announcement()
        self.assertEqual(announcement.state, 'draft')

    def test_all_students_audience_resolves_every_student(self):
        announcement = self._make_announcement(target_audience='all_students')
        partners = announcement._resolve_recipient_partners()
        self.assertIn(self.student.partner_id, partners)
        self.assertIn(self.other_student.partner_id, partners)

    def test_specific_class_audience_filters_by_course_and_batch(self):
        announcement = self._make_announcement(
            target_audience='specific_class',
            course_ids=[(6, 0, [self.course.id])],
            batch_ids=[(6, 0, [self.batch.id])],
        )
        partners = announcement._resolve_recipient_partners()
        self.assertIn(self.student.partner_id, partners)
        self.assertNotIn(self.other_student.partner_id, partners)

    def test_specific_class_audience_without_filters_gets_all_running_enrollments(self):
        announcement = self._make_announcement(
            target_audience='specific_class',
        )
        partners = announcement._resolve_recipient_partners()
        self.assertIn(self.student.partner_id, partners)
        self.assertIn(self.other_student.partner_id, partners)

    def test_recipient_count_is_computed_and_stored(self):
        announcement = self._make_announcement(target_audience='all_students')
        self.assertEqual(announcement.recipient_count, len(announcement._resolve_recipient_partners()))

    def test_publish_without_schedule_publishes_immediately(self):
        announcement = self._make_announcement()
        announcement.action_publish()
        self.assertEqual(announcement.state, 'published')
        self.assertTrue(announcement.published_date)

    def test_publish_with_future_schedule_moves_to_scheduled(self):
        future = fields.Datetime.now() + timedelta(days=1)
        announcement = self._make_announcement(schedule_date=future)
        announcement.action_publish()
        self.assertEqual(announcement.state, 'scheduled')
        self.assertFalse(announcement.published_date)

    def test_cron_publishes_due_scheduled_announcements(self):
        past = fields.Datetime.now() - timedelta(hours=1)
        announcement = self._make_announcement(schedule_date=past)
        announcement.action_publish()
        self.assertEqual(announcement.state, 'scheduled')
        self.env['bxi.announcement']._cron_publish_scheduled()
        self.assertEqual(announcement.state, 'published')
        self.assertTrue(announcement.published_date)

    def test_reset_to_draft_clears_published_date(self):
        announcement = self._make_announcement()
        announcement.action_publish()
        self.assertEqual(announcement.state, 'published')
        announcement.action_reset_to_draft()
        self.assertEqual(announcement.state, 'draft')
        self.assertFalse(announcement.published_date)

    def test_archive_deactivates_announcement(self):
        announcement = self._make_announcement()
        announcement.action_archive_announcement()
        self.assertEqual(announcement.state, 'archived')
        self.assertFalse(announcement.active)

    def test_publish_dispatches_in_app_chatter_message(self):
        announcement = self._make_announcement(
            title='Chatter Test', body='Body for chatter test',
            channel_in_app=True, channel_email=False,
        )
        announcement.action_publish()
        messages = announcement.message_ids.filtered(lambda m: m.subject == 'Chatter Test')
        self.assertTrue(messages)
        self.assertIn(self.student.partner_id, announcement.message_partner_ids)

    def test_publish_with_no_recipients_does_not_error(self):
        announcement = self._make_announcement(
            target_audience='specific_class',
            course_ids=[(6, 0, [self.other_course.id])],
            batch_ids=[(6, 0, [self.batch.id])],
        )
        # No enrollment matches this course/batch combination.
        announcement.action_publish()
        self.assertEqual(announcement.state, 'published')
