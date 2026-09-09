# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAcademicDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.board = cls.env['bxi.board'].create({'name': 'Dashboard Test Board'})
        cls.course = cls.env['op.course'].create({'name': 'Dashboard Class', 'code': 'DASH-C1'})
        cls.project = cls.env['bxi.curriculum.project'].create({'name': 'Dashboard Science Fair'})
        cls.curriculum = cls.env['bxi.curriculum'].create({
            'name': 'Dashboard Curriculum',
            'board_id': cls.board.id,
            'description': 'Curriculum used by the dashboard test',
            'class_ids': [(6, 0, [cls.course.id])],
            'project_ids': [(6, 0, [cls.project.id])],
        })

    def test_get_dashboard_data_structure(self):
        data = self.env['bxi.academic.dashboard'].get_dashboard_data()

        self.assertIn('kpis', data)
        self.assertIn('curricula', data)
        self.assertIn('lesson_plans', data)
        self.assertIn('calendar_events', data)

        expected_kpis = {
            'total_curriculum', 'active_curriculums', 'upcoming_events',
            'pending_approvals', 'lesson_plans',
        }
        self.assertEqual(expected_kpis, set(data['kpis'].keys()))
        self.assertGreaterEqual(data['kpis']['total_curriculum'], 1)
        self.assertGreaterEqual(data['kpis']['active_curriculums'], 1)

    def test_curriculum_card_reflects_classes_and_projects(self):
        data = self.env['bxi.academic.dashboard'].get_dashboard_data()
        card = next(c for c in data['curricula'] if c['id'] == self.curriculum.id)
        self.assertEqual(card['board'], self.board.name)
        self.assertIn(self.course.name, card['classes'])
        self.assertIn(self.project.name, card['projects'])
        self.assertEqual(card['approval_status'], 'draft')
        self.assertFalse(card['locked'])

    def test_locking_curriculum_drops_it_from_active_count(self):
        before = self.env['bxi.academic.dashboard'].get_dashboard_data()['kpis']['active_curriculums']
        self.curriculum.action_toggle_lock()
        after = self.env['bxi.academic.dashboard'].get_dashboard_data()['kpis']['active_curriculums']
        self.assertEqual(after, before - 1)
