"""Shared fixtures for the new tests.

Kept separate from the existing ``test_timetable_common.py`` so we
don't disturb the pre-existing suite. Provides one small helper class
with course/batch/faculty/subject/students already wired up.
"""

from datetime import datetime, timedelta

from odoo import fields
from odoo.tests import common


class SessionFixtureCase(common.TransactionCase):
    """TransactionCase with a ready-made course + batch + faculty +
    subject + a few students, plus a `_make_session` helper.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Session = cls.env['op.session']
        cls.Course = cls.env['op.course']
        cls.Batch = cls.env['op.batch']
        cls.Faculty = cls.env['op.faculty']
        cls.Subject = cls.env['op.subject']
        cls.Student = cls.env['op.student']
        cls.Users = cls.env['res.users']
        cls.Partner = cls.env['res.partner']

        # Build our own small school instead of relying on openeducat demo
        # records, which aren't there on a database created without demo
        # data (that left course_id empty and every session create failed).
        cls.course = cls.Course.create({'name': 'TT Fixture Class', 'code': 'TTFIX-C'})
        cls.batch = cls.Batch.create({
            'name': 'TT Fixture Section', 'code': 'TTFIX-B', 'course_id': cls.course.id,
            'start_date': '2026-01-01', 'end_date': '2027-12-31',
        })
        cls.subject = cls.Subject.create({'name': 'TT Fixture Maths', 'code': 'TTFIX-S'})
        faculty_user = cls.Users.create({
            'name': 'TT Fixture Teacher', 'login': 'ttfix_teacher',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.faculty = cls.Faculty.create({
            'first_name': 'TT', 'last_name': 'Fixture', 'gender': 'male',
            'birth_date': '1985-01-01', 'user_id': faculty_user.id,
        })
        cls.students = cls.Student
        portal = cls.env.ref('base.group_portal')
        for index in range(3):
            user = cls.Users.create({
                'name': 'TT Fixture Student %s' % index, 'login': 'ttfix_student_%s' % index,
                'group_ids': [(6, 0, [portal.id])],
            })
            student = cls.Student.create({
                'first_name': 'TT', 'last_name': 'Student %s' % index, 'gender': 'm',
                'gr_no': 'TTFIX-%s' % index, 'user_id': user.id,
            })
            cls.env['op.student.course'].create({
                'student_id': student.id, 'course_id': cls.course.id, 'batch_id': cls.batch.id,
            })
            cls.students |= student

    @classmethod
    def _safe_ref(cls, xml_id):
        return cls.env.ref(xml_id, raise_if_not_found=False)

    def _make_session(self, start=None, end=None, **overrides):
        """Build a valid ``op.session`` dict + create it."""
        start = start or datetime(2026, 7, 20, 10, 0)
        end = end or datetime(2026, 7, 20, 11, 0)
        values = {
            'start_datetime': fields.Datetime.to_string(start),
            'end_datetime': fields.Datetime.to_string(end),
            'course_id': self.course.id,
            'faculty_id': self.faculty.id,
            'batch_id': self.batch.id,
            'subject_id': self.subject.id,
        }
        values.update(overrides)
        return self.Session.create(values)

    @staticmethod
    def _dt(y, m, d, hh=0, mm=0):
        return datetime(y, m, d, hh, mm)

    @staticmethod
    def _dt_shift(base, **kwargs):
        return base + timedelta(**kwargs)
