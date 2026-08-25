# -*- coding: utf-8 -*-

{
    'name': 'School Notice Board',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Post and browse school notices for students, teachers and parents',
    'description': """
        School Notice Board
        =====================
        - Post a notice with a category, message body, target audience and
          an optional expiry date.
        - Notices go live immediately on posting; there is no draft/publish
          workflow.
        - Notices past their expiry date stay visible but are visually
          flagged, and can be filtered out from the board.
        - Notices can be pinned to keep them at the top of the board; pin
          status is set manually and is not affected by expiry.
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'openeducat_core',
        'openeducat_parent',
    ],
    'data': [
        'security/notice_groups.xml',
        'security/notice_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/mail_template_data.xml',
        'views/notice_views.xml',
        'views/notice_menu.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
