# -*- coding: utf-8 -*-

{
    'name': 'Student Onboarding',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Guided 3-step backend wizard for onboarding new students',
    'description': """
        Student Onboarding
        ===================
        - Guided 3-step intake: Basic Information, Academic Details, Upload Documents
        - Face capture reuses the existing webcam "CLICK IMAGE" widget
        - On completion, creates the Student record, links/creates the
          Parent/Guardian, and carries over the uploaded documents
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'openeducat_core',
        'openeducat_parent',
        'sttl_face_attendance',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/student_onboarding_security.xml',
        'data/ir_sequence_data.xml',
        'views/student_onboarding_views.xml',
        'views/student_view.xml',
        'menu/student_onboarding_menu.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
