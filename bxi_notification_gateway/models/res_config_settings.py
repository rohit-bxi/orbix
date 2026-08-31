# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    msg91_auth_key = fields.Char(
        string='MSG91 Auth Key', config_parameter='bxi_notification_gateway.msg91_auth_key')
    msg91_sender_id = fields.Char(
        string='MSG91 Sender ID', config_parameter='bxi_notification_gateway.msg91_sender_id')
    msg91_otp_template_id = fields.Char(
        string='MSG91 OTP Template ID',
        help='Flow/template ID of the SMS template used to deliver the OTP code. '
             'Must contain a ##OTP## (or equivalent) placeholder.',
        config_parameter='bxi_notification_gateway.msg91_otp_template_id')
