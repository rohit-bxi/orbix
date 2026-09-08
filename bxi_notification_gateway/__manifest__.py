# -*- coding: utf-8 -*-

{
    'name': 'Orbix Notification Gateway',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'SMS/OTP provider integration (MSG91) for the Orbix mobile app and existing SMS-flagged features',
    'description': """
        Orbix Notification Gateway
        ===========================
        Backend-only SMS/OTP integration, consumed via the Orbix API layer
        (bxi_api). Owns:

        - MSG91 credentials (auth key, sender ID, OTP flow/template ID),
          configured under Settings.
        - A generic `send_sms(phone, message)` service other modules can
          call.
        - Phone-number OTP: generate + send a one-time code, then verify it
          server-side (the code itself is generated and checked in Odoo,
          not by MSG91 - MSG91 is only used to deliver the SMS).
        - `/api/v1/otp/request` and `/api/v1/otp/verify` endpoints.
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'base',
        'bxi_api',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
