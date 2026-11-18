# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVisitor(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.department = cls.env['hr.department'].create({'name': 'Visitor Test Office'})
        cls.host = cls.env['hr.employee'].create({'name': 'Visitor Test Host', 'department_id': cls.department.id})
        cls.visitor = cls.env['visitor.data'].create({
            'v_name': 'Vera Visitor', 'v_company': 'Acme', 'v_phn': '+91 98765 43210', 'I_AM': 'guest'})

    def _visit(self, visitor=None):
        return self.env['visit.data'].create({'v_name': (visitor or self.visitor).id, 'employee_id': self.host.id})

    def test_sequence_assigned(self):
        self.assertNotEqual(self.visitor.visitor_seq, 'New')
        other = self.env['visitor.data'].create({
            'v_name': 'Otto', 'v_company': 'Acme', 'v_phn': '9876500000', 'I_AM': 'supplier'})
        self.assertNotEqual(other.visitor_seq, self.visitor.visitor_seq)

    def test_phone_validation(self):
        with self.assertRaises(ValidationError):
            self.env['visitor.data'].create({'v_name': 'Short', 'v_company': 'X', 'v_phn': '12345', 'I_AM': 'guest'})
        with self.assertRaises(ValidationError):
            self.env['visitor.data'].create({'v_name': 'Long', 'v_company': 'X', 'v_phn': '1' * 16, 'I_AM': 'guest'})

    def test_check_in_and_out(self):
        visit = self._visit()
        self.assertEqual(visit.state, 'draft')
        # Stored in UTC: within a minute of the server's UTC "now".
        self.assertLess(abs((fields.Datetime.now() - visit.check_in_date).total_seconds()), 60)
        with self.assertRaises(ValidationError):
            visit.check_out_action()
        visit.check_in_action()
        self.assertEqual(visit.state, 'checkin')
        self.assertEqual(visit.entry_count, 1)
        with self.assertRaises(ValidationError):
            visit.check_in_action()
        visit.check_out_action()
        self.assertEqual(visit.state, 'checkout')
        self.assertTrue(visit.check_out_date)
        # A second visit by the same person updates the entry count on both.
        second = self._visit()
        second.check_in_action()
        self.assertEqual((visit.entry_count, second.entry_count), (2, 2))

    def test_visit_shows_visitor_and_host_details(self):
        visit = self._visit()
        self.assertEqual((visit.v_company, visit.I_AM, visit.v_phn), ('Acme', 'guest', '+91 98765 43210'))
        self.assertEqual(visit.dept, self.department)

    def test_dashboard_counts(self):
        dashboard = self.env['bxi.visitor.dashboard']
        before = dashboard.get_dashboard_data()
        visit = self._visit()
        visit.check_in_action()
        after = dashboard.get_dashboard_data()
        self.assertEqual(after['kpis']['visits_today']['value'], before['kpis']['visits_today']['value'] + 1)
        self.assertEqual(after['kpis']['currently_checked_in']['value'],
                         before['kpis']['currently_checked_in']['value'] + 1)
        self.assertIn(visit.id, [row['id'] for row in after['visit_list']])
        self.assertIn(self.department.name, after['charts']['department_wise']['labels'])
        visit.check_out_action()
        final = dashboard.get_dashboard_data()
        self.assertEqual(final['kpis']['checked_out_today']['value'], before['kpis']['checked_out_today']['value'] + 1)
