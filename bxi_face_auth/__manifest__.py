# -*- coding: utf-8 -*-

{
    'name': 'Orbix Face Login',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Face-recognition login API for students, teachers and parents',
    'description': """
        Orbix Face Login
        ================
        Backend-only, consumed through the Orbix API (bxi_api). Lets a
        student, teacher or parent log in by face and get the same bearer
        token as a password login.

        - Matching runs on the server (OpenCV Zoo YuNet + SFace models,
          MIT/Apache-2.0, CPU only). Nothing biometric is sent to the app.
        - Own phone: the face is compared with the one account the app
          remembers (login_hint). Registered school kiosks search the
          whole school, with a stricter threshold and a score-gap rule.
        - Liveness: a random head-turn challenge per login, plus an
          optional passive anti-spoof model.
        - Enrolment from the app is reviewed by staff before use; staff
          can also enrol in person. Students need a parent's consent.
        - Face embeddings and photos are stored encrypted (bxi_face_key in
          the Odoo config file), separately from the profile picture.
        - Face sessions must confirm the password/OTP (step-up) before
          sensitive actions.

        See README.md for the API and deployment notes.
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'bxi_api',
        'bxi_api_support',
        'bxi_identity_verification',
        'bxi_notification_gateway',
        'openeducat_parent',
    ],
    'external_dependencies': {
        # PyPI names on purpose: Odoo checks a PyPI name through package
        # metadata, but falls back to *importing* an import name like
        # 'cv2' - which would load OpenCV/numpy before __init__.py can cap
        # their thread pools (see there).
        'python': ['opencv-python-headless', 'numpy'],
    },
    'data': [
        'security/face_groups.xml',
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
