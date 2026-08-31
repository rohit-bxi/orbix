# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    razorpay_key_id = fields.Char(
        string='Razorpay Key ID', config_parameter='bxi_online_fee_payment.razorpay_key_id')
    razorpay_key_secret = fields.Char(
        string='Razorpay Key Secret', config_parameter='bxi_online_fee_payment.razorpay_key_secret')
    razorpay_webhook_secret = fields.Char(
        string='Razorpay Webhook Secret',
        help='Configured on the Razorpay dashboard against the /api/v1/payments/webhook URL.',
        config_parameter='bxi_online_fee_payment.razorpay_webhook_secret')
    online_payment_journal_id = fields.Many2one(
        'account.journal', string='Online Payment Journal',
        domain=[('type', 'in', ('bank', 'cash'))],
        config_parameter='bxi_online_fee_payment.default_journal_id')
