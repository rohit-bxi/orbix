# -*- coding: utf-8 -*-

{
    'name': 'Orbix Notification Gateway',
    'version': '19.0.1.1.0',
    'category': 'Education',
    'summary': 'SMS/OTP (MSG91) and push (FCM) notifications for the Orbix mobile app',
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
        - `/api/v1/otp/request` and `/api/v1/otp/verify` endpoints, plus
          OTP login (`/api/v1/auth/otp-login`) and OTP password reset
          (`/api/v1/auth/password/forgot` + `/reset`).
        - Push notifications: app device registry (bxi.api.device), the
          per-user in-app inbox (bxi.notification, created via
          `_notify(...)`) and the FCM HTTP v1 sender a cron uses to
          deliver each inbox entry to the user's devices.
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
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
        'views/push_views.xml',
    ],
    'external_dependencies': {
        'python': ['google-auth'],
    },
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
