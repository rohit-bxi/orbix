# -*- coding: utf-8 -*-

{
    'name': 'Orbix API',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Token-authenticated REST API layer for the Orbix mobile app',
    'description': """
        Orbix API
        =========
        Backend-only API layer consumed by the Orbix mobile app (Student,
        Teacher, Parent, Admin). This module owns:

        - Opaque bearer-token issuing/validation, independent of Odoo's
          session cookies (the mobile app is not a browser).
        - A `/api/v1/...` controller namespace with a consistent JSON
          response/error envelope.
        - Login (username/password), logout and a `me` endpoint to confirm
          who a token resolves to.

        Every other Orbix API module (notifications, payments, messaging,
        etc.) depends on this one and reuses its auth decorator and
        response helpers rather than building their own.
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
    ],
    'data': [
        'security/api_groups.xml',
        'security/ir.model.access.csv',
        'views/api_token_views.xml',
        'views/api_menu.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
