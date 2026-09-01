# -*- coding: utf-8 -*-

{
    'name': 'Orbix Identity Verification',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Aadhaar and face-photo identity verification for students and parents, via the Orbix API',
    'description': """
        Orbix Identity Verification
        ==============================
        Backend-only identity verification, consumed via the Orbix API
        layer (bxi_api). Owns:

        - `unverified -> pending -> verified/rejected` status for both
          Aadhaar (govt ID number) and a face photo, on both op.student
          and op.parent.
        - Submission endpoints for the mobile app to call.
        - Staff review (Verify/Reject) stays a normal Odoo backend action
          on the student/parent form - there is no separate review app,
          it is a judgment call made by a human, the same way it would be
          made looking at a physical ID card.
        - Face capture reuses sttl_face_attendance's existing
          register_face() rather than adding a second image field.
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'bxi_api',
        'openeducat_core',
        'openeducat_parent',
        'sttl_face_attendance',
    ],
    'data': [
        'security/identity_groups.xml',
        'views/op_student_views.xml',
        'views/op_parent_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
