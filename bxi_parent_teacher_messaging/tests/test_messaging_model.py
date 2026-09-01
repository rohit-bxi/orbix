# -*- coding: utf-8 -*-

from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged('post_install', '-at_install')
class TestBxiMessageThreadModel(TransactionCase):
    """Model-level unit tests for bxi.message.thread, calling the model
    methods directly rather than going through the HTTP controllers
    (those are covered separately in tests/test_messaging.py).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.student = cls.env['op.student'].create({
            'first_name': 'ModelMsg', 'last_name': 'Kid', 'gr_no': 'MMSG-001', 'gender': 'm',
        })

        cls.parent_user = mail_new_test_user(
            cls.env, login='mmsg_parent', groups='base.group_portal', password='ParentPass1!')
        cls.teacher_user = mail_new_test_user(
            cls.env, login='mmsg_teacher', groups='base.group_user', password='TeacherPass1!')

        relationship = cls.env['op.parent.relationship'].search([], limit=1) or cls.env['op.parent.relationship'].create({
            'name': 'Guardian',
        })
        cls.parent = cls.env['op.parent'].create({
            'name': cls.env['res.partner'].create({'name': 'ModelMsg Parent', 'is_parent': True}).id,
            'relationship_id': relationship.id,
            'user_id': cls.parent_user.id,
            'student_ids': [(6, 0, [cls.student.id])],
        })
        cls.teacher = cls.env['op.faculty'].create({
            'first_name': 'ModelMsg', 'last_name': 'Teacher', 'birth_date': '1985-01-01', 'gender': 'female',
            'user_id': cls.teacher_user.id,
        })

    # -- _get_or_create ---------------------------------------------------

    def test_get_or_create_creates_new_thread(self):
        Thread = self.env['bxi.message.thread']
        self.assertEqual(Thread.search_count([
            ('student_id', '=', self.student.id),
            ('parent_id', '=', self.parent.id),
            ('teacher_id', '=', self.teacher.id),
        ]), 0)

        thread = Thread._get_or_create(self.student, self.parent, self.teacher)

        self.assertTrue(thread)
        self.assertEqual(thread.student_id, self.student)
        self.assertEqual(thread.parent_id, self.parent)
        self.assertEqual(thread.teacher_id, self.teacher)

    def test_get_or_create_reuses_existing_thread(self):
        Thread = self.env['bxi.message.thread']
        first = Thread._get_or_create(self.student, self.parent, self.teacher)
        second = Thread._get_or_create(self.student, self.parent, self.teacher)

        self.assertEqual(first.id, second.id)
        self.assertEqual(Thread.search_count([
            ('student_id', '=', self.student.id),
            ('parent_id', '=', self.parent.id),
            ('teacher_id', '=', self.teacher.id),
        ]), 1)

    # -- _compute_message_stats -------------------------------------------

    def test_compute_message_stats_with_no_messages(self):
        thread = self.env['bxi.message.thread']._get_or_create(self.student, self.parent, self.teacher)

        self.assertEqual(thread.message_count, 0)
        self.assertEqual(thread.last_message_at, thread.create_date)

    def test_compute_message_stats_with_messages(self):
        thread = self.env['bxi.message.thread']._get_or_create(self.student, self.parent, self.teacher)
        self.env['bxi.message'].sudo().create({
            'thread_id': thread.id, 'sender_user_id': self.parent_user.id, 'body': 'First message.',
        })
        second = self.env['bxi.message'].sudo().create({
            'thread_id': thread.id, 'sender_user_id': self.teacher_user.id, 'body': 'Second message.',
        })

        self.assertEqual(thread.message_count, 2)
        self.assertEqual(thread.last_message_at, second.create_date)

    # -- _unread_count_for --------------------------------------------------

    def test_unread_count_for_counts_only_other_participants_unread_messages(self):
        thread = self.env['bxi.message.thread']._get_or_create(self.student, self.parent, self.teacher)
        self.env['bxi.message'].sudo().create({
            'thread_id': thread.id, 'sender_user_id': self.teacher_user.id, 'body': 'From teacher.',
        })
        self.env['bxi.message'].sudo().create({
            'thread_id': thread.id, 'sender_user_id': self.parent_user.id, 'body': 'From parent.',
        })

        self.assertEqual(thread._unread_count_for(self.parent_user), 1)
        self.assertEqual(thread._unread_count_for(self.teacher_user), 1)

    def test_unread_count_for_excludes_already_read_messages(self):
        thread = self.env['bxi.message.thread']._get_or_create(self.student, self.parent, self.teacher)
        self.env['bxi.message'].sudo().create({
            'thread_id': thread.id, 'sender_user_id': self.teacher_user.id, 'body': 'From teacher.',
        })

        self.assertEqual(thread._unread_count_for(self.parent_user), 1)
        thread._mark_read_for(self.parent_user)
        self.assertEqual(thread._unread_count_for(self.parent_user), 0)

    # -- _mark_read_for -----------------------------------------------------

    def test_mark_read_for_marks_other_participants_messages(self):
        thread = self.env['bxi.message.thread']._get_or_create(self.student, self.parent, self.teacher)
        message = self.env['bxi.message'].sudo().create({
            'thread_id': thread.id, 'sender_user_id': self.teacher_user.id, 'body': 'From teacher.',
        })
        self.assertFalse(message.read_at)

        thread._mark_read_for(self.parent_user)

        self.assertTrue(message.read_at)

    def test_mark_read_for_does_not_mark_own_messages(self):
        thread = self.env['bxi.message.thread']._get_or_create(self.student, self.parent, self.teacher)
        own_message = self.env['bxi.message'].sudo().create({
            'thread_id': thread.id, 'sender_user_id': self.parent_user.id, 'body': 'From parent.',
        })

        thread._mark_read_for(self.parent_user)

        self.assertFalse(own_message.read_at)
