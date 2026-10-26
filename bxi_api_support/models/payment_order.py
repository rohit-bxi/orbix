# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BxiPaymentOrder(models.Model):
    """Canteen wallet top-ups paid through Razorpay. The wallet is only
    credited from `_reconcile_canteen_topup`, i.e. after /payments/verify
    or the webhook has authenticated the payment - never on request."""
    _inherit = 'bxi.payment.order'

    purpose = fields.Selection(
        selection_add=[('canteen_topup', 'Canteen Wallet Top-up')],
        ondelete={'canteen_topup': 'cascade'})
    faculty_id = fields.Many2one('op.faculty', string='Teacher', index=True, readonly=True)

    @api.model
    def _create_for_canteen_topup(self, amount, user, student=None, faculty=None):
        if amount <= 0:
            raise UserError(_('Enter a top-up amount greater than zero.'))
        return self._create_with_gateway({
            'purpose': 'canteen_topup',
            'student_id': student.id if student else False,
            'faculty_id': faculty.id if faculty else False,
            'amount': amount,
            'user_id': user.id,
        })

    def _reconcile_canteen_topup(self):
        journal = self._default_journal()
        if not journal:
            raise UserError(_('No default online-payment journal is configured (Settings > Orbix Payments).'))
        wizard = self.env['bxi.canteen.wallet.topup.wizard'].sudo().create({
            'patron_type': 'faculty' if self.faculty_id else 'student',
            'student_id': self.student_id.id,
            'faculty_id': self.faculty_id.id,
            'amount': self.amount,
            'payment_method': 'online',
            'post_to_accounting': True,
            'journal_id': journal.id,
        })
        wizard.action_topup()
