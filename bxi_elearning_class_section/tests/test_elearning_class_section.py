# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from psycopg2 import IntegrityError

from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestElearningClassSection(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.class_10 = cls.env['elearning.class'].create({'name': 'Class 10'})
        cls.class_9 = cls.env['elearning.class'].create({'name': 'Class 9'})
        cls.section_a = cls.env['elearning.section'].create({
            'name': 'Section A', 'class_id': cls.class_10.id,
        })
        cls.section_b = cls.env['elearning.section'].create({
            'name': 'Section B', 'class_id': cls.class_10.id,
        })
        cls.section_9a = cls.env['elearning.section'].create({
            'name': 'Section A', 'class_id': cls.class_9.id,
        })
        cls.course = cls.env['slide.channel'].create({
            'name': 'Class 10 Hindi Course',
            'class_id': cls.class_10.id,
            'section_id': cls.section_a.id,
        })

    # --- elearning.class / elearning.section ---

    def test_class_section_count_computed(self):
        self.assertEqual(self.class_10.section_count, 2)
        self.assertEqual(self.class_10.channel_count, 1)

    def test_section_channel_count_computed(self):
        self.assertEqual(self.section_a.channel_count, 1)
        self.assertEqual(self.section_b.channel_count, 0)

    def test_section_requires_class(self):
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env['elearning.section'].create({'name': 'Orphan Section'})

    def test_class_unlink_cascades_sections(self):
        section = self.env['elearning.section'].create({
            'name': 'Temp Section', 'class_id': self.class_9.id,
        })
        self.class_9.unlink()
        self.assertFalse(section.exists())

    # --- slide.channel relation ---

    def test_course_class_section_assignment(self):
        self.assertEqual(self.course.class_id, self.class_10)
        self.assertEqual(self.course.section_id, self.section_a)

    def test_onchange_class_clears_mismatched_section(self):
        course = self.env['slide.channel'].new({
            'name': 'New Course',
            'class_id': self.class_10.id,
            'section_id': self.section_a.id,
        })
        course.class_id = self.class_9.id
        course._onchange_class_id()
        self.assertFalse(course.section_id)

    def test_onchange_class_keeps_matching_section(self):
        course = self.env['slide.channel'].new({
            'name': 'New Course',
            'class_id': self.class_10.id,
            'section_id': self.section_a.id,
        })
        course._onchange_class_id()
        self.assertEqual(course.section_id, self.section_a)

    def test_course_without_class_section_is_valid(self):
        course = self.env['slide.channel'].create({'name': 'Unassigned Course'})
        self.assertFalse(course.class_id)
        self.assertFalse(course.section_id)


@tagged('post_install', '-at_install')
class TestElearningClassSectionWebsite(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.class_10 = cls.env['elearning.class'].create({
            'name': 'Class 10', 'website_published': True,
        })
        cls.class_9 = cls.env['elearning.class'].create({
            'name': 'Class 9', 'website_published': True,
        })
        cls.section_a = cls.env['elearning.section'].create({
            'name': 'Section A', 'class_id': cls.class_10.id, 'website_published': True,
        })
        cls.course_10a = cls.env['slide.channel'].create({
            'name': 'Class 10 Hindi Course',
            'class_id': cls.class_10.id,
            'section_id': cls.section_a.id,
            'is_published': True,
            'enroll': 'public',
            'visibility': 'public',
        })
        cls.course_9 = cls.env['slide.channel'].create({
            'name': 'Class 9 Science Course',
            'class_id': cls.class_9.id,
            'is_published': True,
            'enroll': 'public',
            'visibility': 'public',
        })

    def test_slides_home_lists_all_courses(self):
        response = self.url_open('/slides')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Class 10 Hindi Course', response.content)
        self.assertIn(b'Class 9 Science Course', response.content)

    def test_slides_filtered_by_class_id(self):
        response = self.url_open('/slides?class_id=%d' % self.class_10.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Class 10 Hindi Course', response.content)
        self.assertNotIn(b'Class 9 Science Course', response.content)

    def test_slides_filtered_by_section_id(self):
        response = self.url_open(
            '/slides?class_id=%d&section_id=%d' % (self.class_10.id, self.section_a.id))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Class 10 Hindi Course', response.content)
        self.assertNotIn(b'Class 9 Science Course', response.content)

    def test_course_page_shows_class_and_section(self):
        response = self.url_open('/slides/%s' % self.course_10a.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Class 10', response.content)
        self.assertIn(b'Section A', response.content)
