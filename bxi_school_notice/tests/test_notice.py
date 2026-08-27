from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNotice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({
            'name': 'Notice Course', 'code': 'NTC-C1',
        })
        cls.other_course = cls.env['op.course'].create({
            'name': 'Notice Other Course', 'code': 'NTC-C2',
        })
        cls.batch = cls.env['op.batch'].create({
            'name': 'Notice Batch A', 'code': 'NTC-B1',
            'course_id': cls.course.id,
            'start_date': '2026-01-01', 'end_date': '2026-12-31',
        })
        cls.student = cls.env['op.student'].create({
            'first_name': 'Notice', 'last_name': 'Student',
            'gr_no': 'NTC-001', 'gender': 'f',
        })
        cls.env['op.student.course'].create({
            'student_id': cls.student.id,
            'course_id': cls.course.id,
            'batch_id': cls.batch.id,
            'state': 'running',
        })
        cls.other_student = cls.env['op.student'].create({
            'first_name': 'Other', 'last_name': 'Student',
            'gr_no': 'NTC-002', 'gender': 'm',
        })
        cls.env['op.student.course'].create({
            'student_id': cls.other_student.id,
            'course_id': cls.other_course.id,
            'state': 'running',
        })

    def _make_notice(self, **kwargs):
        vals = {
            'title': 'Test Notice',
            'body': 'This is a test notice body.',
            'target_audience': 'all_students',
        }
        vals.update(kwargs)
        return self.env['bxi.notice'].create(vals)

    def test_sequence_assigned_on_create(self):
        notice = self._make_notice()
        self.assertNotEqual(notice.name, 'New')
        self.assertTrue(notice.name)

    def test_notice_goes_live_immediately_no_draft_state(self):
        # There is no draft/publish workflow: posted_date is set at create.
        notice = self._make_notice()
        self.assertTrue(notice.posted_date)
        self.assertTrue(notice.active)

    def test_specific_class_audience_filters_by_course_and_batch(self):
        notice = self._make_notice(
            target_audience='specific_class',
            course_ids=[(6, 0, [self.course.id])],
            batch_ids=[(6, 0, [self.batch.id])],
        )
        partners = notice._resolve_recipient_partners()
        self.assertIn(self.student.partner_id, partners)
        self.assertNotIn(self.other_student.partner_id, partners)

    def test_all_students_audience_resolves_every_student(self):
        notice = self._make_notice(target_audience='all_students')
        partners = notice._resolve_recipient_partners()
        self.assertIn(self.student.partner_id, partners)
        self.assertIn(self.other_student.partner_id, partners)

    def test_not_expired_when_no_expiry_date(self):
        notice = self._make_notice(expires_on=False)
        self.assertFalse(notice.is_expired)

    def test_is_expired_when_expiry_in_past(self):
        past_date = fields.Date.today() - timedelta(days=1)
        notice = self._make_notice(expires_on=past_date)
        self.assertTrue(notice.is_expired)

    def test_is_not_expired_when_expiry_in_future(self):
        future_date = fields.Date.today() + timedelta(days=5)
        notice = self._make_notice(expires_on=future_date)
        self.assertFalse(notice.is_expired)

    def test_search_is_expired_filters_correctly(self):
        past_date = fields.Date.today() - timedelta(days=1)
        future_date = fields.Date.today() + timedelta(days=5)
        expired_notice = self._make_notice(title='Expired', expires_on=past_date)
        active_notice = self._make_notice(title='Active', expires_on=future_date)
        no_expiry_notice = self._make_notice(title='No Expiry')

        expired_results = self.env['bxi.notice'].search([('is_expired', '=', True)])
        self.assertIn(expired_notice, expired_results)
        self.assertNotIn(active_notice, expired_results)
        self.assertNotIn(no_expiry_notice, expired_results)

        not_expired_results = self.env['bxi.notice'].search([('is_expired', '=', False)])
        self.assertIn(active_notice, not_expired_results)
        self.assertIn(no_expiry_notice, not_expired_results)
        self.assertNotIn(expired_notice, not_expired_results)

    def test_toggle_pin_flips_state(self):
        notice = self._make_notice()
        self.assertFalse(notice.is_pinned)
        notice.action_toggle_pin()
        self.assertTrue(notice.is_pinned)
        notice.action_toggle_pin()
        self.assertFalse(notice.is_pinned)

    def test_pinned_notices_ordered_first(self):
        unpinned = self._make_notice(title='Unpinned')
        pinned = self._make_notice(title='Pinned')
        pinned.action_toggle_pin()
        notices = self.env['bxi.notice'].search([('id', 'in', [unpinned.id, pinned.id])])
        self.assertEqual(notices[0], pinned)

    def test_create_subscribes_recipients_and_posts_note(self):
        notice = self._make_notice(target_audience='all_students')
        self.assertIn(self.student.partner_id, notice.message_partner_ids)
        notes = notice.message_ids.filtered(lambda m: m.subtype_id.internal)
        self.assertTrue(notes)

    def test_write_on_notify_field_resends_notification(self):
        notice = self._make_notice(title='Original Title')
        initial_message_count = len(notice.message_ids)
        notice.write({'title': 'Updated Title'})
        self.assertGreater(len(notice.message_ids), initial_message_count)

    def test_write_on_non_notify_field_does_not_resend_notification(self):
        notice = self._make_notice()
        initial_message_count = len(notice.message_ids)
        notice.write({'is_pinned': True})
        self.assertEqual(len(notice.message_ids), initial_message_count)
