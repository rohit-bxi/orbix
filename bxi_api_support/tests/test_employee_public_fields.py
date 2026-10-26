# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEmployeePublicFields(TransactionCase):
    """A teacher (no HR rights) must be able to load employee records - the
    Time Off overview and /leaves both do - even though the school modules
    add stored columns to hr.employee."""

    def test_non_hr_user_can_prefetch_employee(self):
        user = self.env['res.users'].create({
            'name': 'Public Fields Teacher', 'login': 'public_fields_teacher',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('openeducat_core.group_op_faculty').id])],
        })
        employee = self.env['hr.employee'].create({'name': 'Public Fields Teacher', 'user_id': user.id})
        colleague = self.env['hr.employee'].create({'name': 'A Colleague'})
        self.env.invalidate_all()
        # Attribute access prefetches every stored column of the model.
        as_teacher = self.env['hr.employee'].with_user(user).browse([employee.id, colleague.id])
        self.assertEqual(as_teacher[1].name, 'A Colleague')
        self.assertEqual(as_teacher[0].user_id, user)
        public = set(self.env['hr.employee.public']._fields)
        for field in ('student_id', 'is_health_staff', 'health_role', 'license_no'):
            self.assertIn(field, public)
