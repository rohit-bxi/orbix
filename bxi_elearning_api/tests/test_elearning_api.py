# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import base64

from odoo.tests import HttpCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user

# Smallest valid PDF the mimetype sniffer recognises.
PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'


@tagged('post_install', '-at_install')
class TestBxiElearningApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student_user = mail_new_test_user(
            cls.env, login='elapi_student', password='StudentPass1!', groups='base.group_portal')
        cls.other_user = mail_new_test_user(
            cls.env, login='elapi_other', password='OtherPass1!', groups='base.group_portal')
        cls.grade = cls.env['elearning.class'].create({'name': 'ElApi Grade 6'})
        cls.section = cls.env['elearning.section'].create({'name': 'ElApi 6A', 'class_id': cls.grade.id})
        cls.other_grade = cls.env['elearning.class'].create({'name': 'ElApi Grade 7'})
        cls.course = cls.env['slide.channel'].create({
            'name': 'ElApi Fractions', 'class_id': cls.grade.id, 'section_id': cls.section.id,
            'enroll': 'public', 'visibility': 'connected', 'is_published': True,
        })
        cls.chapter = cls.env['slide.slide'].create({
            'name': 'ElApi Basics', 'channel_id': cls.course.id, 'is_category': True, 'sequence': 1,
            'is_published': True,
        })
        cls.article = cls.env['slide.slide'].create({
            'name': 'ElApi What is a fraction', 'channel_id': cls.course.id, 'slide_category': 'article',
            'html_content': '<p>Half</p>', 'is_published': True, 'sequence': 2,
        })
        cls.pdf = cls.env['slide.slide'].create({
            'name': 'ElApi Worksheet', 'channel_id': cls.course.id, 'slide_category': 'document',
            'binary_content': base64.b64encode(PDF), 'is_published': True, 'sequence': 3, 'is_preview': True,
        })
        cls.invite_only = cls.env['slide.channel'].create({
            'name': 'ElApi Olympiad', 'class_id': cls.other_grade.id, 'enroll': 'invite', 'visibility': 'members',
            'is_published': True,
        })
        cls.draft = cls.env['slide.channel'].create({'name': 'ElApi Draft', 'class_id': cls.grade.id,
                                                     'is_published': False})

    def _headers(self, login='elapi_student', password='StudentPass1!'):
        resp = self.url_open('/api/v1/auth/login', json={'login': login, 'password': password})
        return {'Authorization': f'Bearer {resp.json()["data"]["token"]}'}

    def _post(self, path, headers=None):
        return self.url_open(path, headers=headers or self._headers(), json={}, method='POST')

    def test_requires_auth(self):
        self.assertEqual(self.url_open('/api/v1/elearning/courses').status_code, 401)

    def test_classes_and_courses(self):
        headers = self._headers()
        classes = self.url_open('/api/v1/elearning/classes', headers=headers).json()['data']['classes']
        grade = next(c for c in classes if c['id'] == self.grade.id)
        self.assertEqual(grade['course_count'], 1)
        self.assertEqual(grade['sections'][0]['course_count'], 1)
        courses = self.url_open(f'/api/v1/elearning/courses?class_id={self.grade.id}', headers=headers).json()['data']
        ids = [c['id'] for c in courses['courses']]
        self.assertEqual(ids, [self.course.id])  # the draft course is hidden
        everything = self.url_open('/api/v1/elearning/courses', headers=headers).json()['data']['courses']
        self.assertNotIn(self.invite_only.id, [c['id'] for c in everything])  # members-only, not invited
        self.assertEqual(self.url_open(f'/api/v1/elearning/courses/{self.draft.id}', headers=headers).status_code, 404)

    def test_course_detail_join_and_complete(self):
        headers = self._headers()
        detail = self.url_open(f'/api/v1/elearning/courses/{self.course.id}', headers=headers).json()['data']
        self.assertFalse(detail['is_member'])
        self.assertTrue(detail['can_join'])
        self.assertEqual(detail['sections'][0]['name'], 'ElApi Basics')
        lessons = detail['sections'][0]['lessons']
        self.assertEqual([l['id'] for l in lessons], [self.article.id, self.pdf.id])
        self.assertEqual([l['locked'] for l in lessons], [True, False])
        # Members-only content: the article needs joining, the preview PDF doesn't.
        self.assertEqual(self.url_open(f'/api/v1/elearning/lessons/{self.article.id}', headers=headers)
                         .json()['error']['code'], 'join_required')
        pdf = self.url_open(f'/api/v1/elearning/lessons/{self.pdf.id}/file', headers=headers)
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.headers['Content-Type'], 'application/pdf')
        self.assertEqual(self._post(f'/api/v1/elearning/lessons/{self.pdf.id}/complete', headers)
                         .json()['error']['code'], 'join_required')

        joined = self._post(f'/api/v1/elearning/courses/{self.course.id}/join', headers)
        self.assertEqual(joined.status_code, 200, joined.text)
        self.assertTrue(joined.json()['data']['is_member'])
        self.assertEqual(joined.json()['data']['completion'], 0)
        lesson = self.url_open(f'/api/v1/elearning/lessons/{self.article.id}', headers=headers).json()['data']
        self.assertEqual(lesson['html_content'], '<p>Half</p>')
        done = self._post(f'/api/v1/elearning/lessons/{self.article.id}/complete', headers)
        self.assertEqual(done.status_code, 200, done.text)
        self.assertTrue(done.json()['data']['completed'])
        self.assertEqual(done.json()['data']['course']['completion'], 50)
        mine = self.url_open('/api/v1/elearning/courses?joined=1', headers=headers).json()['data']['courses']
        self.assertEqual([c['id'] for c in mine], [self.course.id])
        # Another user's progress is their own.
        other = self.url_open(f'/api/v1/elearning/courses/{self.course.id}', headers=self._headers(
            'elapi_other', 'OtherPass1!')).json()['data']
        self.assertFalse(other['is_member'])

    def test_invitation_only(self):
        headers = self._headers()
        self.assertEqual(self._post(f'/api/v1/elearning/courses/{self.invite_only.id}/join', headers).status_code, 404)
        self.invite_only.sudo()._action_add_members(self.student_user.partner_id, member_status='invited')
        joined = self._post(f'/api/v1/elearning/courses/{self.invite_only.id}/join', headers)
        self.assertEqual(joined.status_code, 200, joined.text)
        self.assertTrue(joined.json()['data']['is_member'])


    def test_reader_modes_language_and_audio(self):
        self.article.write({
            'html_content': '<p>Algebra uses symbols.</p>', 'completion_time': 0.25, 'bxi_level': 'intermediate',
            'bxi_learning_objectives': 'Understand expressions\n- Identify variables\n\n',
            'bxi_video_url': 'https://www.youtube.com/watch?v=abc',
        })
        headers = self._headers()
        self._post(f'/api/v1/elearning/courses/{self.course.id}/join', headers)
        data = self.url_open(f'/api/v1/elearning/lessons/{self.article.id}', headers=headers).json()['data']
        self.assertEqual(data['read_minutes'], 15)
        self.assertEqual(data['level'], 'intermediate')
        self.assertEqual(data['learning_objectives'], ['Understand expressions', 'Identify variables'])
        self.assertTrue(data['modes']['read'])
        self.assertEqual(data['modes']['listen'], {'available': True, 'audio': False, 'text_to_speech': True})
        self.assertEqual(data['modes']['watch']['video_url'], 'https://www.youtube.com/watch?v=abc')
        self.assertIn('Algebra uses symbols.', data['tts_text'])
        self.assertIn('en_US', [lang['code'] for lang in data['languages']])
        no_audio = self.url_open(f'/api/v1/elearning/lessons/{self.article.id}/audio', headers=headers)
        self.assertEqual(no_audio.json()['error']['code'], 'no_audio')

        self.article.bxi_audio = base64.b64encode(b'ID3\x03\x00\x00\x00\x00\x00\x00audio')
        self.article.bxi_audio_filename = 'chapter1.mp3'
        audio = self.url_open(f'/api/v1/elearning/lessons/{self.article.id}/audio', headers=headers)
        self.assertEqual(audio.status_code, 200)
        self.assertTrue(audio.headers['Content-Type'].startswith('audio/'))
        self.assertTrue(self.url_open(f'/api/v1/elearning/lessons/{self.article.id}', headers=headers)
                        .json()['data']['modes']['listen']['audio'])

        bad_lang = self.url_open(f'/api/v1/elearning/lessons/{self.article.id}?lang=xx_XX', headers=headers)
        self.assertEqual(bad_lang.json()['error']['code'], 'invalid_language')
        self.env['res.lang']._activate_lang('fr_FR')
        self.article.with_context(lang='fr_FR').bxi_learning_objectives = 'Comprendre les expressions'
        french = self.url_open(f'/api/v1/elearning/lessons/{self.article.id}?lang=fr_FR', headers=headers).json()['data']
        self.assertEqual(french['language'], 'fr_FR')
        self.assertEqual(french['learning_objectives'], ['Comprendre les expressions'])


@tagged('post_install', '-at_install')
class TestBxiElearningSmartBook(HttpCase):
    """The Smart Books list and reader: chapter progress, the lesson quiz
    ("Quick Check") and the saved reading position."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mail_new_test_user(cls.env, login='elsb_student', password='StudentPass1!', groups='base.group_portal')
        grade = cls.env['elearning.class'].create({'name': 'ElSb Grade 9'})
        cls.tag = cls.env['slide.channel.tag'].create({
            'name': 'ElSb Algebra', 'group_id': cls.env['slide.channel.tag.group'].create({'name': 'ElSb'}).id})
        cls.course = cls.env['slide.channel'].create({
            'name': 'ElSb Algebra Book', 'class_id': grade.id, 'enroll': 'public', 'visibility': 'connected',
            'is_published': True, 'tag_ids': [(6, 0, cls.tag.ids)]})
        Slide = cls.env['slide.slide']
        cls.ch1 = Slide.create({'name': 'ElSb Chapter 1', 'channel_id': cls.course.id, 'slide_category': 'article',
                                'html_content': '<p>Algebra</p>', 'is_published': True, 'sequence': 1,
                                'completion_time': 0.25})
        cls.ch2 = Slide.create({'name': 'ElSb Chapter 2', 'channel_id': cls.course.id, 'slide_category': 'article',
                                'html_content': '<p>More</p>', 'is_published': True, 'sequence': 2,
                                'completion_time': 0.5})
        question = cls.env['slide.question'].create({'question': 'Coefficient of x in 5x + 3?', 'slide_id': cls.ch1.id})
        cls.right = cls.env['slide.answer'].create({'question_id': question.id, 'text_value': '5', 'is_correct': True})
        cls.wrong = cls.env['slide.answer'].create({'question_id': question.id, 'text_value': '3',
                                                    'is_correct': False, 'comment': 'That is the constant.'})

    def _headers(self):
        resp = self.url_open('/api/v1/auth/login', json={'login': 'elsb_student', 'password': 'StudentPass1!'})
        return {'Authorization': f'Bearer {resp.json()["data"]["token"]}'}

    def _post(self, path, body, headers):
        return self.url_open(path, headers=headers, json=body, method='POST')

    def test_progress_quiz_and_position(self):
        headers = self._headers()
        self.assertEqual(self._post(f'/api/v1/elearning/lessons/{self.ch1.id}/quiz/submit',
                                    {'answer_ids': [self.right.id]}, headers).json()['error']['code'], 'join_required')
        self._post(f'/api/v1/elearning/courses/{self.course.id}/join', {}, headers)

        listing = self.url_open(f'/api/v1/elearning/courses?tag_id={self.tag.id}', headers=headers).json()['data']
        progress = listing['courses'][0]['progress']
        self.assertEqual((progress['chapter_index'], progress['chapter_count'], progress['current_lesson']['id'],
                          progress['hours_left']), (1, 2, self.ch1.id, 0.75))

        quiz = self.url_open(f'/api/v1/elearning/lessons/{self.ch1.id}/quiz', headers=headers).json()['data']
        self.assertEqual(len(quiz['questions']), 1)
        self.assertIsNone(quiz['questions'][0]['answers'][0]['is_correct'], 'Not revealed before passing.')
        failed = self._post(f'/api/v1/elearning/lessons/{self.ch1.id}/quiz/submit',
                            {'answer_ids': [self.wrong.id]}, headers).json()['data']
        self.assertFalse(failed['passed'])
        self.assertEqual(failed['answers'][0]['comment'], 'That is the constant.')
        self.assertEqual(self._post(f'/api/v1/elearning/lessons/{self.ch1.id}/quiz/submit', {'answer_ids': []},
                                    headers).json()['error']['code'], 'quiz_incomplete')
        passed = self._post(f'/api/v1/elearning/lessons/{self.ch1.id}/quiz/submit',
                            {'answer_ids': [self.right.id]}, headers).json()['data']
        self.assertTrue(passed['passed'] and passed['completed'])
        self.assertEqual(passed['attempts'], 2)
        self.assertEqual(self._post(f'/api/v1/elearning/lessons/{self.ch1.id}/quiz/submit',
                                    {'answer_ids': [self.right.id]}, headers).json()['error']['code'], 'quiz_done')

        in_progress = self.url_open('/api/v1/elearning/courses?in_progress=1', headers=headers).json()['data']
        self.assertEqual(in_progress['courses'][0]['progress']['chapter_index'], 2, 'Continue from chapter 2.')

        saved = self._post(f'/api/v1/elearning/lessons/{self.ch2.id}/position', {'page': 9, 'total_pages': 45},
                           headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        lesson = self.url_open(f'/api/v1/elearning/lessons/{self.ch2.id}', headers=headers).json()['data']
        self.assertEqual((lesson['position']['page'], lesson['position']['percent']), (9, 20.0))
        self.assertEqual((lesson['previous_lesson']['id'], lesson['next_lesson']), (self.ch1.id, None))
        self.assertEqual(self._post(f'/api/v1/elearning/lessons/{self.ch2.id}/position', {'page': 50,
                                    'total_pages': 45}, headers).json()['error']['code'], 'invalid_position')

