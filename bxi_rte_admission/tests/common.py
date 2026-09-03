# -*- coding: utf-8 -*-

from odoo import fields
from odoo.tests.common import TransactionCase


class TestRteAdmissionCommon(TransactionCase):
    """Shared fixtures for bxi_rte_admission tests.

    Builds a minimal, self-contained op.course / op.academic.year /
    op.admission.register trio (no reliance on demo data) that every test
    module in this package can reuse.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.academic_year = cls.env['op.academic.year'].create({
            'name': 'RTE Test AY',
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today().replace(year=fields.Date.today().year + 1),
        })

        cls.course = cls.env['op.course'].create({
            'name': 'RTE Test Course',
            'code': 'RTEC01',
            'total_intake': 40,
            'rte_active': True,
        })

        cls.register = cls.env['op.admission.register'].create({
            'name': 'RTE Test Register',
            'start_date': fields.Date.today().replace(month=1, day=1),
            'end_date': fields.Date.today().replace(month=12, day=31),
            'course_id': cls.course.id,
            'minimum_age_criteria': 0,
            'min_count': 1,
            'max_count': 40,
        })

    def _get_relationship(self):
        relationship = self.env['op.parent.relationship'].search([], limit=1)
        if not relationship:
            relationship = self.env['op.parent.relationship'].create(
                {'name': 'Guardian'})
        return relationship

    def _make_admission(self, **kwargs):
        counter = getattr(self, '_admission_counter', 0) + 1
        self._admission_counter = counter
        vals = {
            'name': 'RTE Applicant %s' % counter,
            'first_name': 'RTE',
            'last_name': 'Applicant%s' % counter,
            'birth_date': fields.Date.today().replace(
                year=fields.Date.today().year - 6),
            'course_id': self.course.id,
            'email': 'rte.applicant%s@example.com' % counter,
            'gender': 'm',
            'register_id': self.register.id,
            'rte_aadhaar_number': '%012d' % counter,
            'is_rte_applicant': True,
        }
        vals.update(kwargs)
        return self.env['op.admission'].create(vals)
