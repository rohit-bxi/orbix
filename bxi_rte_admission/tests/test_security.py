# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields
from odoo.tests.common import tagged

from .common import TestRteAdmissionCommon


@tagged('post_install', '-at_install')
class TestRteAdmissionSecurity(TestRteAdmissionCommon):
    """Sanity check for the rte_admission_rule_portal_parent ir.rule:
    portal users may only see their own op.admission records
    (domain_force: [('partner_id', '=', user.partner_id.id)])."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.partner_a = cls.env['res.partner'].create({'name': 'RTE Portal Parent A'})
        cls.partner_b = cls.env['res.partner'].create({'name': 'RTE Portal Parent B'})

        portal_group = cls.env.ref('base.group_portal')
        cls.portal_user_a = cls.env['res.users'].create({
            'name': 'Portal User A',
            'login': 'rte_portal_user_a@example.com',
            'email': 'rte_portal_user_a@example.com',
            'group_ids': [(6, 0, [portal_group.id])],
            'partner_id': cls.partner_a.id,
        })

        cls.admission_a = cls._make_admission_for(cls.partner_a)
        cls.admission_b = cls._make_admission_for(cls.partner_b)

    @classmethod
    def _make_admission_for(cls, partner):
        counter = getattr(cls, '_sec_counter', 0) + 1
        cls._sec_counter = counter
        return cls.env['op.admission'].create({
            'name': 'Portal Applicant %s' % counter,
            'first_name': 'Portal',
            'last_name': 'Applicant%s' % counter,
            'birth_date': fields.Date.today().replace(
                year=fields.Date.today().year - 6),
            'course_id': cls.course.id,
            'email': 'portal.applicant%s@example.com' % counter,
            'gender': 'm',
            'register_id': cls.register.id,
            'is_rte_applicant': True,
            'rte_aadhaar_number': '%012d' % (900000000000 + counter),
            'partner_id': partner.id,
        })

    def test_portal_user_only_sees_own_admission(self):
        visible = self.env['op.admission'].with_user(self.portal_user_a).search([])
        self.assertIn(self.admission_a, visible)
        self.assertNotIn(self.admission_b, visible)

    def test_portal_user_cannot_read_others_record_directly(self):
        # Field values already fetched (e.g. application_number, set by
        # openeducat_admission's create_sequence constraint as the
        # superuser that created the fixture) live in the shared
        # transaction-level cache and would otherwise be returned without
        # a fresh access check. Invalidate first so this actually exercises
        # ir.rule enforcement rather than a cache hit.
        self.admission_b.invalidate_recordset()
        AdmissionAsPortal = self.env['op.admission'].with_user(self.portal_user_a)
        with self.assertRaises(Exception):
            AdmissionAsPortal.browse(self.admission_b.id).application_number
