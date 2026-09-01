from odoo.tests import HttpCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged('post_install', '-at_install')
class TestBxiParentTeacherMessaging(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.student = cls.env['op.student'].create({
            'first_name': 'Msg', 'last_name': 'Kid', 'gr_no': 'MSG-001', 'gender': 'm',
        })
        cls.other_student = cls.env['op.student'].create({
            'first_name': 'Msg', 'last_name': 'Other', 'gr_no': 'MSG-002', 'gender': 'f',
        })

        cls.parent_user = mail_new_test_user(
            cls.env, login='msg_parent', groups='base.group_portal', password='ParentPass1!')
        cls.teacher_user = mail_new_test_user(
            cls.env, login='msg_teacher', groups='base.group_user', password='TeacherPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='msg_other', groups='base.group_portal', password='OtherPass1!')

        relationship = cls.env['op.parent.relationship'].search([], limit=1) or cls.env['op.parent.relationship'].create({
            'name': 'Guardian',
        })
        cls.parent = cls.env['op.parent'].create({
            'name': cls.env['res.partner'].create({'name': 'Msg Parent', 'is_parent': True}).id,
            'relationship_id': relationship.id,
            'user_id': cls.parent_user.id,
            'student_ids': [(6, 0, [cls.student.id])],
        })
        cls.teacher = cls.env['op.faculty'].create({
            'first_name': 'Msg', 'last_name': 'Teacher', 'birth_date': '1985-01-01', 'gender': 'female',
            'user_id': cls.teacher_user.id,
        })

    def _headers(self, login, password):
        resp = self.url_open('/api/v1/auth/login', json={'login': login, 'password': password})
        return {'Authorization': f'Bearer {resp.json()["data"]["token"]}'}

    def _start_thread(self):
        resp = self.url_open('/api/v1/messages/threads', headers=self._headers('msg_parent', 'ParentPass1!'), json={
            'student_id': self.student.id, 'teacher_id': self.teacher.id,
        })
        return resp

    # -- start thread ----------------------------------------------------------

    def test_start_thread_creates_and_is_idempotent(self):
        first = self._start_thread()
        self.assertEqual(first.status_code, 200)
        thread_id = first.json()['data']['thread_id']

        second = self._start_thread()
        self.assertEqual(second.json()['data']['thread_id'], thread_id)
        self.assertEqual(self.env['bxi.message.thread'].sudo().search_count([]), 1)

    def test_start_thread_for_unlinked_student_forbidden(self):
        resp = self.url_open('/api/v1/messages/threads', headers=self._headers('msg_parent', 'ParentPass1!'), json={
            'student_id': self.other_student.id, 'teacher_id': self.teacher.id,
        })
        self.assertEqual(resp.status_code, 403)

    def test_start_thread_requires_parent_account(self):
        resp = self.url_open('/api/v1/messages/threads', headers=self._headers('msg_teacher', 'TeacherPass1!'), json={
            'student_id': self.student.id, 'teacher_id': self.teacher.id,
        })
        self.assertEqual(resp.status_code, 403)

    def test_start_thread_missing_fields(self):
        resp = self.url_open('/api/v1/messages/threads', headers=self._headers('msg_parent', 'ParentPass1!'), json={
            'student_id': self.student.id,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_fields')

    def test_start_thread_student_not_found(self):
        resp = self.url_open('/api/v1/messages/threads', headers=self._headers('msg_parent', 'ParentPass1!'), json={
            'student_id': 999999, 'teacher_id': self.teacher.id,
        })
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error']['code'], 'not_found')

    def test_start_thread_teacher_not_found(self):
        resp = self.url_open('/api/v1/messages/threads', headers=self._headers('msg_parent', 'ParentPass1!'), json={
            'student_id': self.student.id, 'teacher_id': 999999,
        })
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error']['code'], 'not_found')

    def test_list_threads_requires_auth(self):
        resp = self.url_open('/api/v1/messages/threads', headers={'Authorization': 'Bearer bogus-token'})
        self.assertEqual(resp.status_code, 401)

    # -- send / list messages ----------------------------------------------------

    def test_parent_and_teacher_can_message_each_other(self):
        thread_id = self._start_thread().json()['data']['thread_id']
        parent_headers = self._headers('msg_parent', 'ParentPass1!')
        teacher_headers = self._headers('msg_teacher', 'TeacherPass1!')

        send_resp = self.url_open(f'/api/v1/messages/threads/{thread_id}/messages', headers=parent_headers, json={
            'body': 'How is my child doing in class?',
        })
        self.assertEqual(send_resp.status_code, 200)

        reply_resp = self.url_open(f'/api/v1/messages/threads/{thread_id}/messages', headers=teacher_headers, json={
            'body': 'Doing great, very engaged in class discussions.',
        })
        self.assertEqual(reply_resp.status_code, 200)

        list_resp = self.url_open(f'/api/v1/messages/threads/{thread_id}/messages', headers=parent_headers)
        messages = list_resp.json()['data']['messages']
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]['body'], 'How is my child doing in class?')
        self.assertEqual(messages[1]['body'], 'Doing great, very engaged in class discussions.')

    def test_unrelated_user_cannot_send_or_list(self):
        thread_id = self._start_thread().json()['data']['thread_id']
        other_headers = self._headers('msg_other', 'OtherPass1!')

        send_resp = self.url_open(f'/api/v1/messages/threads/{thread_id}/messages', headers=other_headers, json={'body': 'hi'})
        self.assertEqual(send_resp.status_code, 403)

        list_resp = self.url_open(f'/api/v1/messages/threads/{thread_id}/messages', headers=other_headers)
        self.assertEqual(list_resp.status_code, 403)

    def test_send_empty_body_rejected(self):
        thread_id = self._start_thread().json()['data']['thread_id']
        resp = self.url_open(f'/api/v1/messages/threads/{thread_id}/messages', headers=self._headers('msg_parent', 'ParentPass1!'), json={
            'body': '   ',
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_messages_thread_not_found(self):
        resp = self.url_open('/api/v1/messages/threads/999999/messages', headers=self._headers('msg_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error']['code'], 'not_found')

    def test_send_message_thread_not_found(self):
        resp = self.url_open('/api/v1/messages/threads/999999/messages', headers=self._headers('msg_parent', 'ParentPass1!'), json={
            'body': 'hi',
        })
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error']['code'], 'not_found')

    def test_message_read_at_reflected_in_list(self):
        thread_id = self._start_thread().json()['data']['thread_id']
        parent_headers = self._headers('msg_parent', 'ParentPass1!')
        teacher_headers = self._headers('msg_teacher', 'TeacherPass1!')

        self.url_open(f'/api/v1/messages/threads/{thread_id}/messages', headers=teacher_headers, json={'body': 'Unread update.'})

        before = self.url_open(f'/api/v1/messages/threads/{thread_id}/messages', headers=parent_headers).json()['data']['messages']
        self.assertIsNone(before[0]['read_at'])

        self.url_open(f'/api/v1/messages/threads/{thread_id}/read', headers=parent_headers, method='POST')

        after = self.url_open(f'/api/v1/messages/threads/{thread_id}/messages', headers=parent_headers).json()['data']['messages']
        self.assertIsNotNone(after[0]['read_at'])

    # -- list threads / unread counts --------------------------------------------

    def test_list_threads_shows_thread_for_both_participants(self):
        self._start_thread()
        parent_threads = self.url_open('/api/v1/messages/threads', headers=self._headers('msg_parent', 'ParentPass1!')).json()['data']['threads']
        teacher_threads = self.url_open('/api/v1/messages/threads', headers=self._headers('msg_teacher', 'TeacherPass1!')).json()['data']['threads']
        other_threads = self.url_open('/api/v1/messages/threads', headers=self._headers('msg_other', 'OtherPass1!')).json()['data']['threads']

        self.assertEqual(len(parent_threads), 1)
        self.assertEqual(len(teacher_threads), 1)
        self.assertEqual(len(other_threads), 0)

    def test_unread_count_and_mark_read(self):
        thread_id = self._start_thread().json()['data']['thread_id']
        teacher_headers = self._headers('msg_teacher', 'TeacherPass1!')
        parent_headers = self._headers('msg_parent', 'ParentPass1!')

        self.url_open(f'/api/v1/messages/threads/{thread_id}/messages', headers=teacher_headers, json={'body': 'Update on homework.'})

        parent_threads = self.url_open('/api/v1/messages/threads', headers=parent_headers).json()['data']['threads']
        self.assertEqual(parent_threads[0]['unread_count'], 1)

        mark_resp = self.url_open(f'/api/v1/messages/threads/{thread_id}/read', headers=parent_headers, method='POST')
        self.assertEqual(mark_resp.status_code, 200)

        parent_threads_after = self.url_open('/api/v1/messages/threads', headers=parent_headers).json()['data']['threads']
        self.assertEqual(parent_threads_after[0]['unread_count'], 0)

    def test_mark_read_forbidden_for_unrelated_user(self):
        thread_id = self._start_thread().json()['data']['thread_id']
        resp = self.url_open(f'/api/v1/messages/threads/{thread_id}/read', headers=self._headers('msg_other', 'OtherPass1!'), method='POST')
        self.assertEqual(resp.status_code, 403)

    def test_mark_read_thread_not_found(self):
        resp = self.url_open('/api/v1/messages/threads/999999/read', headers=self._headers('msg_parent', 'ParentPass1!'), method='POST')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error']['code'], 'not_found')

    def test_mark_read_does_not_mark_own_messages(self):
        thread_id = self._start_thread().json()['data']['thread_id']
        parent_headers = self._headers('msg_parent', 'ParentPass1!')

        self.url_open(f'/api/v1/messages/threads/{thread_id}/messages', headers=parent_headers, json={'body': 'From the parent.'})
        self.url_open(f'/api/v1/messages/threads/{thread_id}/read', headers=parent_headers, method='POST')

        messages = self.url_open(f'/api/v1/messages/threads/{thread_id}/messages', headers=parent_headers).json()['data']['messages']
        self.assertIsNone(messages[0]['read_at'])
