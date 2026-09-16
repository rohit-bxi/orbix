# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.tests.common import TransactionCase


class TestParentPortalCommon(TransactionCase):
    """Shared fixtures for bxi_parent_portal tests.

    A parent-portal user only ever reaches op.student rows through
    res.users.child_ids (see student_parent_login_rule in openeducat_parent
    and bxi_student_portal's own ir.rule set), so every fixture here builds
    that link directly rather than going through the op.parent wizard flow.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._counter = 0

        cls.course = cls.env['op.course'].create({
            'name': 'Parent Portal Test Course', 'code': 'PPTC01',
        })
        cls.batch = cls.env['op.batch'].create({
            'name': 'Parent Portal Test Batch', 'code': 'PPTB01', 'course_id': cls.course.id,
            'end_date': fields.Date.today() + timedelta(days=180),
        })

        cls.income_account = cls.env['account.account'].search(
            [('account_type', '=', 'income'), ('company_ids', 'in', cls.env.company.id)], limit=1)
        if not cls.income_account:
            cls.income_account = cls.env['account.account'].create({
                'name': 'Parent Portal Test Income', 'code': 'PPTINC01', 'account_type': 'income',
                'company_ids': [(6, 0, [cls.env.company.id])],
            })
        cls.sale_journal = cls.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', cls.env.company.id)], limit=1)
        if not cls.sale_journal:
            cls.sale_journal = cls.env['account.journal'].create({
                'name': 'Parent Portal Test Sales Journal', 'type': 'sale', 'code': 'PPTSJ01',
            })

    @classmethod
    def _next(cls):
        cls._counter += 1
        return cls._counter

    @classmethod
    def _make_portal_user(cls, login_prefix='portal_user'):
        n = cls._next()
        return mail_new_test_user(
            cls.env, login='%s_%s' % (login_prefix, n), groups='base.group_portal',
            password='PortalPass1!')

    @classmethod
    def _make_student(cls, **kwargs):
        n = cls._next()
        vals = {
            'first_name': 'Child', 'last_name': 'No%s' % n,
            'gender': 'm', 'gr_no': 'PPGR-%s' % n,
        }
        vals.update(kwargs)
        student = cls.env['op.student'].create(vals)
        # Mirrors op.student.create_student_user(): the login shares the
        # student's own delegated partner_id, not a fresh one - portal
        # ir.rules on account.move (child_of user.commercial_partner_id)
        # only resolve correctly when the login and the student are the
        # same partner, exactly as production student logins are set up.
        portal_group = cls.env.ref('base.group_portal')
        student_user = cls.env['res.users'].create({
            'name': student.name,
            'login': 'child_%s@example.com' % n,
            'email': 'child_%s@example.com' % n,
            'partner_id': student.partner_id.id,
            'group_ids': [(6, 0, [portal_group.id])],
            'password': 'PortalPass1!',
        })
        student.user_id = student_user.id
        cls.env['op.student.course'].create({
            'student_id': student.id, 'course_id': cls.course.id, 'batch_id': cls.batch.id,
        })
        return student

    @classmethod
    def _make_parent_user(cls, children):
        """children: a single op.student recordset (possibly with several
        records) to link onto the new parent's res.users.child_ids."""
        parent_user = cls._make_portal_user('parent')
        parent_user.child_ids = [(6, 0, children.mapped('user_id').ids)]
        # account.move's own portal ir.rule (shipped in the 'account' module,
        # untouched by bxi_parent_portal/hooks.py) only grants a parent read
        # access to a child's invoice when the child's partner is nested
        # under the parent's via parent_id - res.users.child_ids alone (used
        # by op.student/op.attendance.line/etc. ir.rules) doesn't cover it.
        for child in children:
            child.partner_id.parent_id = parent_user.partner_id.id
        return parent_user

    @classmethod
    def _make_attendance(cls, student, presents):
        n = cls._next()
        register = cls.env['op.attendance.register'].create({
            'name': 'Parent Portal Attendance Register %s' % n, 'code': 'PPAR%s' % n,
            'course_id': cls.course.id, 'batch_id': cls.batch.id,
        })
        today = fields.Date.today()
        lines = cls.env['op.attendance.line']
        for i, present in enumerate(presents):
            sheet = cls.env['op.attendance.sheet'].create({
                'register_id': register.id,
                'attendance_date': today - timedelta(days=i),
                'state': 'done',
            })
            lines |= cls.env['op.attendance.line'].create({
                'attendance_id': sheet.id, 'student_id': student.id,
                'present': present, 'absent': not present,
            })
        return lines

    @classmethod
    def _make_fee_invoice(cls, student, amount, invoice_state='posted'):
        invoice = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': student.partner_id.id,
            'journal_id': cls.sale_journal.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Parent Portal Test Fee',
                'account_id': cls.income_account.id,
                'price_unit': amount, 'quantity': 1.0, 'tax_ids': [(5, 0, 0)],
            })],
        })
        if invoice_state == 'posted':
            invoice.action_post()
        elif invoice_state == 'cancel':
            invoice.button_cancel()
        return cls.env['op.student.fees.details'].create({
            'student_id': student.id, 'amount': amount,
            'date': fields.Date.today(), 'invoice_id': invoice.id,
        })
