from odoo.tests import HttpCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged('post_install', '-at_install')
class TestBxiTeacherSupport(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.teacher_user = mail_new_test_user(
            cls.env, login='support_teacher', groups='base.group_user', password='TeacherPass1!')
        cls.env['bxi.faq'].create([
            {'question': 'How do I reset my password?', 'answer': '<p>Go to Settings.</p>', 'category': 'Account'},
            {'question': 'Where do I mark attendance?', 'answer': '<p>Attendance tab.</p>', 'category': 'Attendance'},
            {'question': 'Archived FAQ', 'answer': '<p>hidden</p>', 'active': False},
        ])

        cls.student_user = mail_new_test_user(
            cls.env, login='support_student', groups='base.group_portal', password='StudentPass1!')
        cls.student = cls.env['op.student'].create({
            'first_name': 'Support', 'last_name': 'Student', 'gr_no': 'SUP-001', 'gender': 'f',
            'user_id': cls.student_user.id,
        })

        cls.parent_user = mail_new_test_user(
            cls.env, login='support_parent', groups='base.group_portal', password='ParentPass1!')
        relationship = cls.env['op.parent.relationship'].search([], limit=1) or cls.env['op.parent.relationship'].create({
            'name': 'Guardian',
        })
        cls.parent = cls.env['op.parent'].create({
            'name': cls.env['res.partner'].create({'name': 'Support Parent', 'is_parent': True}).id,
            'relationship_id': relationship.id,
            'user_id': cls.parent_user.id,
            'student_ids': [(6, 0, [cls.student.id])],
        })

        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Support', 'last_name': 'Teacher', 'birth_date': '1985-01-01', 'gender': 'male',
            'user_id': cls.teacher_user.id,
        })

    def _headers(self, login, password):
        resp = self.url_open('/api/v1/auth/login', json={'login': login, 'password': password})
        return {'Authorization': f'Bearer {resp.json()["data"]["token"]}'}

    def test_list_faqs_excludes_archived(self):
        resp = self.url_open('/api/v1/support/faqs', headers=self._headers('support_teacher', 'TeacherPass1!'))
        self.assertEqual(resp.status_code, 200)
        faqs = resp.json()['data']['faqs']
        self.assertEqual(len(faqs), 2)

    def test_list_faqs_filtered_by_category(self):
        resp = self.url_open(
            '/api/v1/support/faqs?category=Attendance', headers=self._headers('support_teacher', 'TeacherPass1!'))
        faqs = resp.json()['data']['faqs']
        self.assertEqual(len(faqs), 1)
        self.assertEqual(faqs[0]['category'], 'Attendance')

    def test_list_faqs_filtered_by_audience(self):
        self.env['bxi.faq'].create({
            'question': 'Parent only FAQ', 'answer': '<p>x</p>', 'audience': 'parent',
        })
        resp = self.url_open(
            '/api/v1/support/faqs?audience=parent', headers=self._headers('support_parent', 'ParentPass1!'))
        faqs = resp.json()['data']['faqs']
        # 2 'all' + the 1 parent-specific FAQ
        self.assertEqual(len(faqs), 3)
        self.assertIn('Parent only FAQ', [f['question'] for f in faqs])

    def test_create_ticket_assigns_teacher_support_team(self):
        headers = self._headers('support_teacher', 'TeacherPass1!')
        resp = self.url_open('/api/v1/support/tickets', headers=headers, json={
            'subject': 'Cannot access my timetable', 'description': 'Blank screen on load.',
        })
        self.assertEqual(resp.status_code, 200)
        ticket_id = resp.json()['data']['id']
        ticket = self.env['helpdesk.ticket'].sudo().browse(ticket_id)
        self.assertEqual(ticket.team_id, self.env.ref('bxi_teacher_support.helpdesk_team_teacher_support'))
        self.assertEqual(ticket.partner_id, self.faculty.partner_id)

    def test_create_ticket_missing_subject_rejected(self):
        resp = self.url_open('/api/v1/support/tickets', headers=self._headers('support_teacher', 'TeacherPass1!'), json={
            'description': 'no subject',
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_ticket_with_category_tag(self):
        headers = self._headers('support_teacher', 'TeacherPass1!')
        tag = self.env.ref('bxi_teacher_support.tag_login_issues')
        resp = self.url_open('/api/v1/support/tickets', headers=headers, json={
            'subject': 'Cannot log in', 'category_tag_id': tag.id,
        })
        ticket = self.env['helpdesk.ticket'].sudo().browse(resp.json()['data']['id'])
        self.assertIn(tag, ticket.tag_ids)

    def test_list_tickets_only_shows_own(self):
        headers = self._headers('support_teacher', 'TeacherPass1!')
        self.url_open('/api/v1/support/tickets', headers=headers, json={'subject': 'My ticket'})

        other_user = mail_new_test_user(self.env, login='support_other', groups='base.group_user', password='OtherPass1!')
        self.env['helpdesk.ticket'].sudo().create({'name': 'Someone else ticket', 'partner_id': other_user.partner_id.id})

        resp = self.url_open('/api/v1/support/tickets', headers=headers)
        tickets = resp.json()['data']['tickets']
        self.assertTrue(all(t['name'] != 'Someone else ticket' for t in tickets))
        self.assertTrue(any(t['name'] == 'My ticket' for t in tickets))

    def test_endpoints_require_auth(self):
        self.assertEqual(self.url_open('/api/v1/support/faqs').status_code, 401)
        self.assertEqual(self.url_open('/api/v1/support/tickets').status_code, 401)

    def test_create_ticket_requires_auth(self):
        resp = self.url_open('/api/v1/support/tickets', json={'subject': 'No token'})
        self.assertEqual(resp.status_code, 401)

    def test_invalid_token_rejected(self):
        headers = {'Authorization': 'Bearer not-a-real-token'}
        resp = self.url_open('/api/v1/support/faqs', headers=headers)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()['error']['code'], 'unauthorized')

    def test_list_faqs_unknown_category_returns_empty(self):
        resp = self.url_open(
            '/api/v1/support/faqs?category=NoSuchCategory',
            headers=self._headers('support_teacher', 'TeacherPass1!'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['faqs'], [])

    def test_list_faqs_ordered_by_sequence(self):
        self.env['bxi.faq'].create([
            {'question': 'Second', 'answer': '<p>b</p>', 'category': 'Order', 'sequence': 20},
            {'question': 'First', 'answer': '<p>a</p>', 'category': 'Order', 'sequence': 5},
        ])
        resp = self.url_open(
            '/api/v1/support/faqs?category=Order',
            headers=self._headers('support_teacher', 'TeacherPass1!'))
        faqs = resp.json()['data']['faqs']
        self.assertEqual([f['question'] for f in faqs], ['First', 'Second'])

    def test_create_ticket_blank_subject_rejected(self):
        headers = self._headers('support_teacher', 'TeacherPass1!')
        resp = self.url_open('/api/v1/support/tickets', headers=headers, json={
            'subject': '   ', 'description': 'whitespace only subject',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'missing_subject')

    def test_create_ticket_without_description_defaults_empty(self):
        headers = self._headers('support_teacher', 'TeacherPass1!')
        resp = self.url_open('/api/v1/support/tickets', headers=headers, json={
            'subject': 'No description provided',
        })
        self.assertEqual(resp.status_code, 200)
        ticket = self.env['helpdesk.ticket'].sudo().browse(resp.json()['data']['id'])
        self.assertFalse(ticket.description)

    # -- role resolution ----------------------------------------------------

    def test_create_ticket_resolves_student_role(self):
        headers = self._headers('support_student', 'StudentPass1!')
        resp = self.url_open('/api/v1/support/tickets', headers=headers, json={'subject': 'Student issue'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['role'], 'student')
        ticket = self.env['helpdesk.ticket'].sudo().browse(resp.json()['data']['id'])
        self.assertEqual(ticket.partner_id, self.student.partner_id)
        self.assertIn(self.env.ref('bxi_teacher_support.tag_role_student'), ticket.tag_ids)

    def test_create_ticket_resolves_parent_role(self):
        headers = self._headers('support_parent', 'ParentPass1!')
        resp = self.url_open('/api/v1/support/tickets', headers=headers, json={'subject': 'Parent issue'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['role'], 'parent')
        ticket = self.env['helpdesk.ticket'].sudo().browse(resp.json()['data']['id'])
        self.assertEqual(ticket.partner_id, self.parent.name)
        self.assertIn(self.env.ref('bxi_teacher_support.tag_role_parent'), ticket.tag_ids)

    def test_create_ticket_resolves_teacher_role(self):
        headers = self._headers('support_teacher', 'TeacherPass1!')
        resp = self.url_open('/api/v1/support/tickets', headers=headers, json={'subject': 'Teacher issue'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['role'], 'teacher')
        self.assertIn(
            self.env.ref('bxi_teacher_support.tag_role_teacher'),
            self.env['helpdesk.ticket'].sudo().browse(resp.json()['data']['id']).tag_ids)

    # -- ticket detail / reply -----------------------------------------------

    def test_get_ticket_returns_messages(self):
        headers = self._headers('support_student', 'StudentPass1!')
        create_resp = self.url_open('/api/v1/support/tickets', headers=headers, json={'subject': 'Need help'})
        ticket_id = create_resp.json()['data']['id']

        resp = self.url_open(f'/api/v1/support/tickets/{ticket_id}', headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['id'], ticket_id)

    def test_get_ticket_not_owned_returns_404(self):
        headers_student = self._headers('support_student', 'StudentPass1!')
        create_resp = self.url_open('/api/v1/support/tickets', headers=headers_student, json={'subject': 'Private'})
        ticket_id = create_resp.json()['data']['id']

        headers_teacher = self._headers('support_teacher', 'TeacherPass1!')
        resp = self.url_open(f'/api/v1/support/tickets/{ticket_id}', headers=headers_teacher)
        self.assertEqual(resp.status_code, 404)

    def test_reply_ticket_posts_message(self):
        headers = self._headers('support_student', 'StudentPass1!')
        create_resp = self.url_open('/api/v1/support/tickets', headers=headers, json={'subject': 'Need help'})
        ticket_id = create_resp.json()['data']['id']

        resp = self.url_open(f'/api/v1/support/tickets/{ticket_id}/reply', headers=headers, json={'body': 'Any update?'})
        self.assertEqual(resp.status_code, 200)

        detail = self.url_open(f'/api/v1/support/tickets/{ticket_id}', headers=headers)
        bodies = [m['body'] for m in detail.json()['data']['messages']]
        self.assertTrue(any('Any update?' in b for b in bodies))

    def test_reply_rejected_for_non_owner(self):
        headers_student = self._headers('support_student', 'StudentPass1!')
        create_resp = self.url_open('/api/v1/support/tickets', headers=headers_student, json={'subject': 'Private'})
        ticket_id = create_resp.json()['data']['id']

        headers_teacher = self._headers('support_teacher', 'TeacherPass1!')
        resp = self.url_open(f'/api/v1/support/tickets/{ticket_id}/reply', headers=headers_teacher, json={'body': 'Nope'})
        self.assertEqual(resp.status_code, 404)

    def test_reply_missing_body_rejected(self):
        headers = self._headers('support_student', 'StudentPass1!')
        create_resp = self.url_open('/api/v1/support/tickets', headers=headers, json={'subject': 'Need help'})
        ticket_id = create_resp.json()['data']['id']

        resp = self.url_open(f'/api/v1/support/tickets/{ticket_id}/reply', headers=headers, json={'body': ''})
        self.assertEqual(resp.status_code, 400)
