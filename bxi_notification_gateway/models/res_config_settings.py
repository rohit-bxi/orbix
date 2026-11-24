# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, models

from .otp_request import DELIVERY_MODES


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    bxi_otp_delivery = fields.Selection(
        DELIVERY_MODES, string='Send codes and logins by', default='auto',
        help='How one-time codes (login, password reset, confirmations) and new logins reach people. '
             'Automatic sends an SMS once MSG91 is set up below and an email until then.',
        config_parameter='bxi_notification_gateway.otp_delivery')
    msg91_auth_key = fields.Char(
        string='MSG91 Auth Key', config_parameter='bxi_notification_gateway.msg91_auth_key')
    msg91_sender_id = fields.Char(
        string='MSG91 Sender ID', config_parameter='bxi_notification_gateway.msg91_sender_id')
    msg91_otp_template_id = fields.Char(
        string='MSG91 OTP Template ID',
        help='Flow/template ID of the SMS template used to deliver the OTP code. '
             'Must contain a ##OTP## (or equivalent) placeholder.',
        config_parameter='bxi_notification_gateway.msg91_otp_template_id')
    msg91_credentials_template_id = fields.Char(
        string='MSG91 Login Credentials Template ID',
        help='Flow/template ID of the SMS that carries a new login: it must contain the '
             'USERNAME and PASSWORD variables (the password is a one-time password).',
        config_parameter='bxi_notification_gateway.msg91_credentials_template_id')
    fcm_project_id = fields.Char(
        string='Firebase Project ID', config_parameter='bxi_notification_gateway.fcm_project_id')
    fcm_service_account_json = fields.Char(
        string='Firebase Service Account (JSON)',
        help='Full JSON key of a Google service account with the "Firebase Cloud Messaging API Admin" '
             'role, used to send push notifications to the Orbix app.',
        config_parameter='bxi_notification_gateway.fcm_service_account_json')
