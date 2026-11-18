# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
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

    def _data(self):
        return self.env['bxi.academic.dashboard'].get_dashboard_data()

    def test_pending_approvals_count_draft_curricula(self):
        before = self._data()['kpis']['pending_approvals']
        extra = self.env['bxi.curriculum'].create({
            'name': 'Dashboard Draft Curriculum', 'board_id': self.board.id, 'description': 'Draft'})
        self.assertEqual(self._data()['kpis']['pending_approvals'], before + 1)
        extra.action_approve()
        self.assertEqual(self._data()['kpis']['pending_approvals'], before)

    def test_upcoming_events_window_and_calendar(self):
        now = fields.Datetime.now()
        before = self._data()['kpis']['upcoming_events']
        soon = self.env['bxi.ptm.meeting'].create({
            'name': 'Dashboard PTM Soon', 'start_datetime': now + timedelta(days=10),
            'end_datetime': now + timedelta(days=10, hours=2), 'venue': 'Hall A',
            'class_ids': [(6, 0, self.course.ids)]})
        self.env['bxi.ptm.meeting'].create({
            'name': 'Dashboard PTM Later', 'start_datetime': now + timedelta(days=60),
            'end_datetime': now + timedelta(days=60, hours=2), 'venue': 'Hall A',
            'class_ids': [(6, 0, self.course.ids)]})
        holiday = self.env['resource.calendar.leaves'].create({
            'name': 'Dashboard Holiday', 'date_from': now + timedelta(days=5),
            'date_to': now + timedelta(days=5, hours=8), 'resource_id': False, 'calendar_id': False})
        data = self._data()
        # Only the PTM inside the 30-day window counts as upcoming.
        self.assertEqual(data['kpis']['upcoming_events'], before + 1)
        events = data['calendar_events']
        titles = [e['title'] for e in events]
        self.assertIn(soon.name, titles)
        self.assertIn(holiday.name, titles)
        self.assertEqual(next(e for e in events if e['title'] == soon.name)['detail'], 'Hall A')
        self.assertEqual(next(e for e in events if e['title'] == holiday.name)['type'], 'holiday')
        self.assertEqual([e['date'] for e in events], sorted(e['date'] for e in events))

    def test_curriculum_card_lists_mapped_subjects(self):
        subject = self.env['op.subject'].create({'name': 'Dashboard Biology', 'code': 'DASH-BIO'})
        teacher = self.env['op.faculty'].create({
            'first_name': 'Dash', 'last_name': 'Teacher', 'gender': 'female', 'birth_date': '1985-01-01'})
        self.env['bxi.subject.mapping'].create({
            'subject_id': subject.id, 'class_id': self.course.id, 'teacher_id': teacher.id,
            'curriculum_id': self.curriculum.id})
        card = next(c for c in self._data()['curricula'] if c['id'] == self.curriculum.id)
        self.assertEqual(card['subjects'], ['Dashboard Biology'])
