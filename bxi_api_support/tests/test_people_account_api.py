# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase
from .test_people_management_api import PIXEL

PDF = base64.b64encode(b'%PDF-1.4\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n').decode()


@tagged('post_install', '-at_install')
class TestBxiApiSupportPeopleAccount(ApiSupportHttpCase):
    """User management: Account & Security (logins, one-time passwords,
    credentials, ID verification), teacher documents and the teacher
    lesson & evaluation permissions."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course, cls.batch = cls._create_class('UMA')
        cls.office_user = mail_new_test_user(
            cls.env, login='uma_office', groups='base.group_user,openeducat_core.group_op_back_office_admin',
            password='OfficePass1!')
        cls.reviewer_user = mail_new_test_user(
            cls.env, login='uma_reviewer', groups='base.group_user,bxi_identity_verification.group_identity_reviewer',
            password='ReviewPass1!')
        cls.relationship = cls.env['op.parent.relationship'].search([], limit=1) or \
            cls.env['op.parent.relationship'].create({'name': 'Guardian'})
        cls.job = cls.env['hr.job'].create({'name': 'UMA Lecturer'})
        cls.env.company.email = 'office@uma-school.test'  # the sender of login emails

    def setUp(self):
        super().setUp()
        # Odoo skips SMTP in tests and leaves mails queued: record what would
        # be sent and mark it sent, as a working mail server would.
        self.sent_mails = []
        sent_mails = self.sent_mails

        def fake_send(mails, *args, **kwargs):
            for mail in mails:
                sent_mails.append({'to': mail.email_to, 'body': str(mail.body_html)})
            mails.write({'state': 'sent'})
            return True

        patcher = patch.object(type(self.env['mail.mail']), '_send', fake_send)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _office(self):
        return self._headers('uma_office', 'OfficePass1!')

    def _post(self, url, body, headers=None):
        # method= because url_open sends a GET when the JSON body is {}.
        return self.url_open(url, headers=headers or self._office(), json=body, method='POST')

    def _login(self, login, password):
        return self.url_open('/api/v1/auth/login', json={'login': login, 'password': password})

    def _teacher(self, **extra):
        body = {'first_name': 'Ana', 'last_name': 'Account', 'gender': 'female', 'birth_date': '1987-07-07'}
        body.update(extra)
        return self._post('/api/v1/teachers', body)

    def _student(self, roll, **extra):
        body = {'first_name': 'Stu', 'last_name': 'Dent%s' % roll, 'gender': 'm', 'email': 'stu%s@uma.test' % roll,
                'enrollment': {'course_id': self.course.id, 'batch_id': self.batch.id, 'roll_number': roll}}
        body.update(extra)
        return self._post('/api/v1/students', body)

    # -- logins ----------------------------------------------------------------------------

    def test_teacher_login_with_generated_one_time_password(self):
        resp = self._teacher(designation_id=self.job.id, account={'username': 'ana.account'})
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertTrue(data['account']['has_login'])
        self.assertEqual(data['account']['username'], 'ana.account')
        self.assertTrue(data['account']['must_change_password'])
        self.assertTrue(data['account']['one_time_password_expires_at'])
        otp = data['credentials']['one_time_password']
        self.assertEqual(data['credentials']['reason'], 'not_requested')

        faculty = self.env['op.faculty'].browse(data['id'])
        self.assertTrue(faculty.user_id.has_group('openeducat_core.group_op_faculty'))
        self.assertTrue(faculty.emp_id, 'A teacher login comes with their HR employee.')
        self.assertEqual(faculty.emp_id.job_id, self.job, 'The designation is the employee\'s job position.')

        login = self._login('ana.account', otp)
        self.assertEqual(login.status_code, 200, login.text)
        self.assertTrue(login.json()['data']['user']['must_change_password'])

    def test_typed_password_sent_by_email(self):
        resp = self._teacher(email='ana.mail@uma.test', account={
            'username': 'ana.mail', 'password': 'TypedPass123', 'send_credentials': True, 'channel': 'email'})
        self.assertEqual(resp.status_code, 201, resp.text)
        credentials = resp.json()['data']['credentials']
        self.assertEqual(credentials['channel'], 'email')
        self.assertTrue(credentials['sent'], credentials)
        self.assertNotIn('one_time_password', credentials, 'The office typed it; it is not echoed back.')
        self.assertEqual(self.sent_mails[-1]['to'], 'ana.mail@uma.test')
        self.assertIn('ana.mail', self.sent_mails[-1]['body'])
        self.assertIn('TypedPass123', self.sent_mails[-1]['body'])
        self.assertFalse(self.env['mail.mail'].search([('email_to', '=', 'ana.mail@uma.test')]),
                         'The mail carrying the password does not stay in the database.')
        self.assertEqual(self._login('ana.mail', 'TypedPass123').status_code, 200)

    def test_account_validation_and_rollback(self):
        self._teacher(account={'username': 'taken.login'})
        before = self.env['op.faculty'].search_count([])
        for account, status, code in (
            ({'username': 'TAKEN.login'}, 409, 'login_taken'),
            ({'username': 'weak.pw', 'password': 'short'}, 400, 'invalid_password'),
            ({'username': 'wa.user', 'send_credentials': True, 'channel': 'whatsapp'}, 400, 'invalid_channel'),
            ({'create_login': True}, 400, 'missing_username'),
            ('yes', 400, 'invalid_account'),
        ):
            resp = self._teacher(account=account)
            self.assertEqual(resp.status_code, status, account)
            self.assertEqual(resp.json()['error']['code'], code, account)
        self.assertEqual(self.env['op.faculty'].search_count([]), before, 'Nothing is half-created.')

    def test_student_and_parent_logins(self):
        student = self._student('1', account={'username': 'stu.one', 'send_credentials': True, 'channel': 'sms'})
        self.assertEqual(student.status_code, 201, student.text)
        data = student.json()['data']
        user = self.env['op.student'].browse(data['id']).user_id
        self.assertTrue(user.is_student)
        self.assertTrue(user.has_group('base.group_portal'))
        self.assertFalse(data['credentials']['sent'])
        self.assertEqual(data['credentials']['reason'], 'no_phone')
        self.assertTrue(data['credentials']['one_time_password'], 'Not delivered, so shown once to the office.')

        parent = self._post('/api/v1/parents', {
            'name': 'Paula Parent', 'mobile': '9800012345', 'relationship_id': self.relationship.id,
            'student_ids': [data['id']], 'account': {'username': 'paula.parent', 'password': 'ParentTyped9'}})
        self.assertEqual(parent.status_code, 201, parent.text)
        record = self.env['op.parent'].browse(parent.json()['data']['id'])
        self.assertTrue(record.user_id.is_parent)
        self.assertEqual(record.user_id.child_ids, user)
        self.assertEqual(self._login('paula.parent', 'ParentTyped9').status_code, 200)

        legacy = self._post('/api/v1/parents', {
            'name': 'Legacy Parent', 'mobile': '9800012346', 'relationship_id': self.relationship.id,
            'student_ids': [data['id']], 'email': 'legacy.parent@uma.test', 'create_login': True})
        self.assertEqual(legacy.status_code, 201, legacy.text)
        self.assertEqual(legacy.json()['data']['account']['username'], 'legacy.parent@uma.test')

    def test_account_routes(self):
        data = self._teacher(email='routes@uma.test').json()['data']
        base = '/api/v1/teachers/%s/account' % data['id']
        self.assertEqual(self._post(base + '/status', {'active': False}).json()['error']['code'], 'no_account')
        created = self._post(base, {'create_login': True, 'username': 'route.teacher', 'password': 'RoutePass11'})
        self.assertEqual(created.status_code, 200, created.text)
        token = self._login('route.teacher', 'RoutePass11').json()['data']['token']

        off = self._post(base + '/status', {'active': False})
        self.assertFalse(off.json()['data']['account']['active'])
        self.assertEqual(self.url_open('/api/v1/auth/me', headers={'Authorization': 'Bearer ' + token}).status_code,
                         401, 'Turning sign-in off ends every session.')
        self.assertEqual(self._login('route.teacher', 'RoutePass11').status_code, 401)
        self.assertTrue(self._post(base + '/status', {'active': True}).json()['data']['account']['active'])
        self.assertEqual(self._post(base + '/status', {'active': 'no'}).json()['error']['code'], 'invalid_active')

        reset = self._post(base + '/reset-password', {}).json()['data']
        self.assertEqual(self._login('route.teacher', reset['credentials']['one_time_password']).status_code, 200)
        typed = self._post(base + '/reset-password', {'password': 'BrandNew123'}).json()['data']
        self.assertNotIn('one_time_password', typed['credentials'])
        self.assertEqual(self._login('route.teacher', 'BrandNew123').status_code, 200)

        sent = self._post(base + '/send-credentials', {'channel': 'email'}).json()['data']['credentials']
        self.assertTrue(sent['sent'], sent)
        self.assertEqual(self._login('route.teacher', 'BrandNew123').status_code, 401,
                         'Sending credentials issues a fresh one-time password.')
        sms = self._post(base + '/send-credentials', {'channel': 'sms'}).json()['data']['credentials']
        self.assertFalse(sms['sent'])
        self.assertTrue(sms['one_time_password'])

        renamed = self._post(base, {'username': 'route.teacher2'}).json()['data']
        self.assertEqual(renamed['account']['username'], 'route.teacher2')
        got = self.url_open(base, headers=self._office()).json()['data']
        self.assertEqual(got['account']['username'], 'route.teacher2')
        self.assertEqual(got['id_verification']['status'], 'unverified')

        parent_headers = self._headers('uma_reviewer', 'ReviewPass1!')
        self.assertEqual(self.url_open(base, headers=parent_headers).status_code, 403)
        self.assertEqual(self.url_open('/api/v1/teachers/999999/account', headers=self._office()).status_code, 404)

    def test_office_cannot_touch_an_admin_login_or_its_own(self):
        admin_faculty = self.env['op.faculty'].create({
            'first_name': 'Root', 'last_name': 'Admin', 'gender': 'male', 'birth_date': '1980-01-01',
            'user_id': self.env.ref('base.user_admin').id})
        # The OpenEduCat back-office Manager group implies Settings, so use an
        # academic manager: allowed to manage people, but not an administrator.
        mail_new_test_user(self.env, login='uma_academic', password='AcademicPass1!',
                           groups='base.group_user,bxi_academic_management.group_academic_manager')
        academic = self._headers('uma_academic', 'AcademicPass1!')
        url = '/api/v1/teachers/%s/account/reset-password' % admin_faculty.id
        resp = self._post(url, {}, academic)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._post(url, {}).status_code, 200, 'An administrator may.')
        own = self.env['op.faculty'].create({
            'first_name': 'Office', 'last_name': 'Self', 'gender': 'male', 'birth_date': '1980-01-01',
            'user_id': self.office_user.id})
        resp = self._post('/api/v1/teachers/%s/account/status' % own.id, {'active': False})
        self.assertEqual(resp.json()['error']['code'], 'cannot_deactivate_self')

    def test_face_block_needs_a_login(self):
        resp = self._teacher(face={'enabled': True, 'image': PIXEL})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'no_account')
        self.assertEqual(self._teacher(face={'image': PIXEL}).json()['error']['code'], 'invalid_face')
        if not self.env['bxi.people.service']._face_available():
            resp = self._teacher(account={'username': 'no.face'}, face={'enabled': True, 'image': PIXEL})
            self.assertEqual(resp.json()['error']['code'], 'face_unavailable')
            self.assertFalse(self.env['res.users'].search([('login', '=', 'no.face')]))

    # -- ID verification ---------------------------------------------------------------------

    def test_id_verification_flow(self):
        resp = self._student('2', id_verification={'document': {'data': PDF, 'filename': 'aadhaar.pdf'},
                                                   'doc_type': 'aadhaar'})
        self.assertEqual(resp.status_code, 201, resp.text)
        verification = resp.json()['data']['id_verification']
        self.assertEqual(verification['status'], 'pending')
        self.assertEqual(verification['doc_type'], 'aadhaar')
        self.assertEqual(verification['documents'][0]['mimetype'], 'application/pdf')
        student_id = resp.json()['data']['id']
        base = '/api/v1/students/%s/id-verification' % student_id

        doc_url = '%s/documents/%s' % (base, verification['documents'][0]['id'])
        self.assertEqual(self.url_open(doc_url, headers=self._office()).content[:5], b'%PDF-')

        reviewer = self._headers('uma_reviewer', 'ReviewPass1!')
        self.assertEqual(self._post(base + '/review', {'decision': 'maybe'}, reviewer).json()['error']['code'],
                         'invalid_decision')
        verified = self._post(base + '/review', {'decision': 'verify', 'notes': 'Matches'}, reviewer)
        self.assertEqual(verified.status_code, 200, verified.text)
        self.assertEqual(verified.json()['data']['id_verification']['status'], 'verified')
        self.assertEqual(self._post(base + '/review', {'decision': 'reject'}, reviewer).json()['error']['code'],
                         'invalid_transition')
        self.assertEqual(self._post(base, {'document': PIXEL}, reviewer).status_code, 403,
                         'Reviewers check documents; the office uploads them.')

        text = base64.b64encode(b'just some text').decode()
        self.assertEqual(self._post(base, {'document': text}).json()['error']['code'], 'invalid_file_type')
        self.assertEqual(self._post(base, {}).json()['error']['code'], 'missing_document')
        self.assertEqual(self._post(base, {'document': PIXEL, 'doc_type': 'ration'}).json()['error']['code'],
                         'invalid_doc_type')

        multipart = self.url_open(base, headers=self._office(), data={'doc_type': 'passport'},
                                  files={'file': ('passport.png', base64.b64decode(PIXEL), 'image/png')})
        self.assertEqual(multipart.status_code, 200, multipart.text)
        replaced = multipart.json()['data']['id_verification']
        self.assertEqual(replaced['status'], 'pending', 'A new document goes back to review.')
        self.assertEqual(replaced['doc_type'], 'passport')
        self.assertEqual(len(replaced['documents']), 1, 'The earlier document is replaced.')

    def test_teacher_id_verification(self):
        resp = self._teacher(id_verification={'document': PIXEL})
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(resp.json()['data']['id_verification']['status'], 'pending')

    # -- teacher documents --------------------------------------------------------------------

    def test_teacher_documents(self):
        resp = self._teacher(account={'username': 'doc.teacher', 'password': 'DocTeach123'}, documents=[
            {'doc_type': 'cv', 'file': PDF, 'filename': 'cv.pdf'},
            {'doc_type': 'aadhaar', 'name': 'Aadhaar front', 'file': PIXEL}])
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertEqual(sorted(d['doc_type'] for d in data['documents']), ['aadhaar', 'cv'])
        base = '/api/v1/teachers/%s/documents' % data['id']

        upload = self.url_open(base, headers=self._office(), data={'doc_type': 'certificate', 'name': 'B.Ed'},
                               files={'file': ('bed.pdf', base64.b64decode(PDF), 'application/pdf')})
        self.assertEqual(upload.status_code, 201, upload.text)
        certificate = upload.json()['data']['documents'][0]
        self.assertEqual(certificate['name'], 'B.Ed')
        self.assertEqual(certificate['mimetype'], 'application/pdf')
        self.assertEqual(self._post(base, {'doc_type': 'payslip', 'file': PDF}).json()['error']['code'],
                         'invalid_doc_type')

        listing = self.url_open(base + '?doc_type=certificate', headers=self._office()).json()['data']['documents']
        self.assertEqual([d['id'] for d in listing], [certificate['id']])
        download = self.url_open('%s/%s' % (base, certificate['id']), headers=self._office())
        self.assertEqual(download.content[:5], b'%PDF-')

        own = self._headers('doc.teacher', 'DocTeach123')
        self.url_open('/api/v1/auth/password/change', headers=own,
                      json={'old_password': 'DocTeach123', 'new_password': 'DocTeach456'})
        own = self._headers('doc.teacher', 'DocTeach456')
        self.assertEqual(len(self.url_open(base, headers=own).json()['data']['documents']), 3,
                         'A teacher can read their own documents...')
        self.assertEqual(self._post(base, {'file': PDF}, own).status_code, 403, '...but not upload.')

        deleted = self._post('%s/%s/delete' % (base, certificate['id']), {})
        self.assertTrue(deleted.json()['data']['deleted'])
        self.assertEqual(self.url_open('%s/%s' % (base, certificate['id']), headers=self._office()).status_code, 404)

    # -- lesson & evaluation permissions --------------------------------------------------------

    def test_teacher_permissions_and_assigned_sections(self):
        student = self._create_student('UMA-S1')
        self._enroll(student, self.course, self.batch)
        resp = self._teacher(account={'username': 'perm.teacher', 'password': 'PermTeach123'},
                             permissions={'lesson_plans': False, 'homework': False, 'exam_marks': False,
                                          'reports': False})
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()['data']
        self.assertEqual(data['permissions'], {'lesson_plans': False, 'homework': False,
                                               'evaluate_assignments': True, 'exam_marks': False, 'reports': False})
        self.url_open('/api/v1/auth/password/change', headers=self._headers('perm.teacher', 'PermTeach123'),
                      json={'old_password': 'PermTeach123', 'new_password': 'PermTeach456'})
        teacher = self._headers('perm.teacher', 'PermTeach456')

        me = self.url_open('/api/v1/auth/me', headers=teacher).json()['data']
        self.assertFalse(me['teacher_permissions']['lesson_plans'])
        self.assertTrue(me['teacher_permissions']['evaluate_assignments'])
        for method, url in (('POST', '/api/v1/lesson-plans'), ('POST', '/api/v1/assignments'),
                            ('POST', '/api/v1/exams/999999/marks'), ('GET', '/api/v1/dashboards')):
            resp = self.url_open(url, headers=teacher, json={} if method == 'POST' else None, method=method)
            self.assertEqual(resp.status_code, 403, url)
            self.assertEqual(resp.json()['error']['code'], 'teacher_permission_denied', url)
        accept = self.url_open('/api/v1/assignments/submissions/999999/accept', headers=teacher, json={},
                               method='POST')
        self.assertEqual(accept.status_code, 404, 'Evaluation stays allowed (and finds no such submission).')
        self.assertEqual(self.url_open('/api/v1/dashboards', headers=self._office()).status_code, 200,
                         'The office is never limited by these switches.')

        self.assertEqual(self.url_open('/api/v1/students', headers=teacher).json()['meta']['total'], 0)
        self._post('/api/v1/teachers/%s/update' % data['id'], {
            'assignments': {'batch_ids': [self.batch.id]}, 'permissions': {'lesson_plans': True}})
        listing = self.url_open('/api/v1/students', headers=teacher).json()
        self.assertEqual(listing['meta']['total'], 1, 'An assigned section is one the teacher teaches.')
        plan = self.url_open('/api/v1/lesson-plans', headers=teacher, json={}, method='POST')
        self.assertNotEqual(plan.json()['error']['code'], 'teacher_permission_denied')
        bad = self._post('/api/v1/teachers/%s/update' % data['id'], {'permissions': {'fly': True}})
        self.assertEqual(bad.json()['error']['code'], 'invalid_permissions')
