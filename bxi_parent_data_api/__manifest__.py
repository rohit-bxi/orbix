# -*- coding: utf-8 -*-

{
    'name': 'Orbix Parent Data API',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Read-only exam/results, attendance, timetable and dashboard endpoints for the Orbix mobile app',
    'description': """
        Orbix Parent Data API
        ========================
        Backend-only, consumed via the Orbix API layer (bxi_api). Pure
        read endpoints over data that already exists - no new models, no
        new modeling, just an API surface:

        - Exam results (openeducat_exam marksheet data)
        - Attendance, with a computed present/absent/late summary
          (openeducat_attendance)
        - Timetable / upcoming sessions (openeducat_timetable)
        - A single dashboard endpoint aggregating the above plus the fee
          summary already exposed by bxi_online_fee_payment
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'bxi_api',
        'openeducat_exam',
        'openeducat_attendance',
        'openeducat_timetable',
        'bxi_student_refund_management',
    ],
    'data': [],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
