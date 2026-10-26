# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import HttpCase, tagged

from .common import TestParentPortalCommon


@tagged('post_install', '-at_install')
class TestParentPortalPages(HttpCase, TestParentPortalCommon):

    def test_my_child_requires_auth(self):
        resp = self.url_open('/my/child', allow_redirects=False)
        self.assertIn(resp.status_code, (302, 303))
        self.assertIn('/web/login', resp.headers.get('Location', ''))

    def test_my_child_redirects_straight_to_academics_for_single_child(self):
        child = self._make_student()
        parent_user = self._make_parent_user(child)
        self.authenticate(parent_user.login, 'PortalPass1!')

        resp = self.url_open('/my/child', allow_redirects=False)
        self.assertIn(resp.status_code, (301, 302, 303))
        self.assertEqual(resp.headers.get('Location'), '/my/academics/%d' % child.id)

    def test_my_child_lists_all_children_with_summaries(self):
        child_a = self._make_student()
        child_b = self._make_student()
        self._mark_attendance(child_a, [True, True, False, False])
        self._make_fee_invoice(child_b, 250.0, invoice_state='posted')
        parent_user = self._make_parent_user(child_a | child_b)
        self.authenticate(parent_user.login, 'PortalPass1!')

        resp = self.url_open('/my/child')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(child_a.name, resp.text)
        self.assertIn(child_b.name, resp.text)
        self.assertIn('50.0%', resp.text)
        self.assertIn('250', resp.text)

    def test_my_child_empty_state_when_no_children_linked(self):
        parent_user = self._make_portal_user('lonely_parent')
        self.authenticate(parent_user.login, 'PortalPass1!')

        resp = self.url_open('/my/child')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('No children are linked to this account yet.', resp.text)

    def test_parent_can_view_own_child_academics_page(self):
        child = self._make_student()
        parent_user = self._make_parent_user(child)
        self.authenticate(parent_user.login, 'PortalPass1!')

        resp = self.url_open('/my/academics/%d' % child.id)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(child.name, resp.text)

    def test_parent_cannot_view_unrelated_student_academics_page(self):
        child = self._make_student()
        other_student = self._make_student()
        parent_user = self._make_parent_user(child)
        self.authenticate(parent_user.login, 'PortalPass1!')

        resp = self.url_open('/my/academics/%d' % other_student.id)
        self.assertEqual(resp.status_code, 403)

    def test_portal_home_has_my_children_card(self):
        child = self._make_student()
        parent_user = self._make_parent_user(child)
        self.authenticate(parent_user.login, 'PortalPass1!')
        resp = self.url_open('/my/home')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('href="/my/child"', resp.text)
        self.assertIn('data-placeholder_count="children_count"', resp.text)

    def test_children_counter_reveals_card_for_parent(self):
        parent_user = self._make_parent_user(self._make_student() | self._make_student())
        self.authenticate(parent_user.login, 'PortalPass1!')
        res = self.make_jsonrpc_request('/my/counters', {'counters': ['children_count']})
        self.assertEqual(res, {'children_count': 2})

    def test_children_counter_is_zero_without_children(self):
        parent_user = self._make_portal_user('lonely_parent2')
        self.authenticate(parent_user.login, 'PortalPass1!')
        res = self.make_jsonrpc_request('/my/counters', {'counters': ['children_count']})
        self.assertEqual(res, {'children_count': 0})

    def test_counters_skip_children_when_not_requested(self):
        parent_user = self._make_parent_user(self._make_student())
        self.authenticate(parent_user.login, 'PortalPass1!')
        res = self.make_jsonrpc_request('/my/counters', {'counters': []})
        self.assertEqual(res, {})
