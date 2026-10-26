# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import HttpCase, tagged

from .common import TestStudentPortalCommon


@tagged('post_install', '-at_install')
class TestStudentPortalPages(HttpCase, TestStudentPortalCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student = cls._make_student()

    def test_academics_home_requires_auth(self):
        resp = self.url_open('/my/academics', allow_redirects=False)
        self.assertIn(resp.status_code, (302, 303))
        self.assertIn('/web/login', resp.headers.get('Location', ''))

    def test_academics_home_renders_for_own_student(self):
        self.authenticate(self.student.user_id.login, 'PortalPass1!')
        resp = self.url_open('/my/academics')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.student.name, resp.text)

    def test_attendance_page_shows_computed_percentage(self):
        self._mark_attendance(self.student, [True, True, True, False, False])
        self.authenticate(self.student.user_id.login, 'PortalPass1!')
        resp = self.url_open('/my/academics/attendance')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('60.0%', resp.text)

    def test_exams_page_shows_only_validated_marksheet(self):
        self._make_marksheet(self.student, 80, register_state='validated')
        self._make_marksheet(self.student, 40, register_state='draft')
        self.authenticate(self.student.user_id.login, 'PortalPass1!')
        resp = self.url_open('/my/academics/exams')
        self.assertEqual(resp.status_code, 200)
        # Only the validated marksheet's total (80.0) should show up; the
        # draft register's line (40.0) must stay hidden from the student.
        self.assertIn('80.0', resp.text)
        self.assertNotIn('40.0', resp.text)

    def test_assignments_page_hides_draft_shows_published(self):
        published = self._make_assignment(self.student, state='publish')
        self._make_assignment(self.student, state='draft')
        self.authenticate(self.student.user_id.login, 'PortalPass1!')
        resp = self.url_open('/my/academics/assignments')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(published.name, resp.text)

    def test_library_page_lists_movement(self):
        self._make_library_movement(self.student)
        self.authenticate(self.student.user_id.login, 'PortalPass1!')
        resp = self.url_open('/my/academics/library')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self._library_media.name, resp.text)

    def test_fees_page_shows_due_total(self):
        self._make_fee_invoice(self.student, 500.0, invoice_state='posted')
        self.authenticate(self.student.user_id.login, 'PortalPass1!')
        resp = self.url_open('/my/academics/fees')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('500', resp.text)

    def test_fees_due_excludes_cancelled_invoice(self):
        self._make_fee_invoice(self.student, 500.0, invoice_state='cancel')
        self.authenticate(self.student.user_id.login, 'PortalPass1!')
        resp = self.url_open('/my/academics/fees')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Amount currently due', resp.text)
        self.assertIn('0.00', resp.text)

    def test_unrelated_student_id_is_forbidden(self):
        other_student = self._make_student()
        self.authenticate(self.student.user_id.login, 'PortalPass1!')
        resp = self.url_open('/my/academics/%d' % other_student.id)
        self.assertEqual(resp.status_code, 403)

    def test_nonexistent_student_id_is_missing(self):
        self.authenticate(self.student.user_id.login, 'PortalPass1!')
        resp = self.url_open('/my/academics/999999999')
        self.assertEqual(resp.status_code, 404)

    def test_portal_home_has_academics_card(self):
        self.authenticate(self.student.user_id.login, 'PortalPass1!')
        resp = self.url_open('/my/home')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('href="/my/academics"', resp.text)
        self.assertIn('data-placeholder_count="academics_count"', resp.text)

    def test_academics_counter_reveals_card_for_student(self):
        self.authenticate(self.student.user_id.login, 'PortalPass1!')
        res = self.make_jsonrpc_request('/my/counters', {'counters': ['academics_count']})
        self.assertEqual(res, {'academics_count': 1})

    def test_academics_counter_is_zero_without_student_profile(self):
        user = self._make_portal_user('no_student')
        self.authenticate(user.login, 'PortalPass1!')
        res = self.make_jsonrpc_request('/my/counters', {'counters': ['academics_count']})
        self.assertEqual(res, {'academics_count': 0})

    def test_counters_skip_academics_when_not_requested(self):
        # portal_home_counters.js looks up a card for every returned key,
        # so an unrequested key would throw and leave the spinner running.
        self.authenticate(self.student.user_id.login, 'PortalPass1!')
        res = self.make_jsonrpc_request('/my/counters', {'counters': []})
        self.assertEqual(res, {})
