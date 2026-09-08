# -*- coding: utf-8 -*-

{
    'name': 'Orbix Help & Support',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Student/Parent/Teacher support tickets (via the generic helpdesk app) and a simple FAQ list, via the Orbix API',
    'description': """
        Orbix Help & Support
        ==============================
        Backend-only, consumed via the Orbix API layer (bxi_api). Two
        small pieces:

        - Configures one shared "Help & Support" helpdesk team plus the 6
          category tags the Figma design specifies (Account & Profile,
          Technical Errors, Timetable & Calendar, Assignments &
          Evaluation, Attendance & Reports, Login Issues) and 3 role tags
          (Student, Parent, Teacher), and exposes create-ticket /
          list-my-tickets / ticket-detail / reply endpoints over the
          existing helpdesk app - no new ticketing engine. The caller's
          role (student/parent/teacher) is auto-resolved from the
          logged-in user.
        - A small `bxi.faq` model (question, answer, category, audience,
          order) with a list endpoint filterable by audience.
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'base',
        'bxi_api',
        'helpdesk',
        'openeducat_core',
        'openeducat_parent',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/helpdesk_team_data.xml',
        'views/faq_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
