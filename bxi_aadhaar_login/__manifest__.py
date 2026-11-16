# -*- coding: utf-8 -*-

{
    'name': 'Orbix Aadhaar Login',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Students, teachers and parents log in with their Aadhaar number - password or emailed code',
    'description': """
        Orbix Aadhaar Login
        ===================
        A second way to log in, for schools in India: the Aadhaar number
        (on the student / teacher / parent record, bxi_identity_verification)
        identifies the account, and the person proves it is them with
        either their normal password or a one-time code emailed to the
        address on their school record. Username / email login is unchanged.

        - API: `/api/v1/auth/login` with `"login_type": "aadhaar"`,
          `/api/v1/auth/aadhaar/otp-request`, `/api/v1/auth/aadhaar/otp-login`,
          `/api/v1/auth/aadhaar/config`, admin settings routes.
        - Web: the /web/login form accepts an Aadhaar number, and
          /web/login/aadhaar-code signs in with an emailed code.
        - Settings per school: on/off, email code on/off, verified numbers
          only, and which roles may use it.

        The number is only used to find the account; UIDAI is never
        contacted. It is looked up through a keyed hash, never logged and
        never returned in full.
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'base',
        'web',
        'bxi_api',
        'bxi_notification_gateway',
        'bxi_identity_verification',
    ],
    'data': [
        'views/res_config_settings_views.xml',
        'views/web_login_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
