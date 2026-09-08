# -*- coding: utf-8 -*-

{
    'name': 'Academic Management',
    'version': '19.0.2.0.0',
    'category': 'Education',
    'summary': 'Curriculum boards, class assignment, smart books and subject-teacher mapping',
    'description': """
        Academic Management
        ====================
        - Curriculum: define curriculum boards (e.g. CBSE, ICSE, State Board) and assign Classes to them
        - Smart Book: curriculum-linked books, built on the existing Library media model
        - Subject Mapping: map Subject + Class + Curriculum to a Teacher
        - Event: schedule Parent-Teacher Meetings for one or more Classes
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'base',
        'mail',
        'hr_holidays',
        'openeducat_core',
        'openeducat_library',
    ],
    'data': [
        'security/academic_management_groups.xml',
        'security/ir.model.access.csv',
        'security/academic_management_security.xml',
        'data/mail_template_data.xml',
        'views/board_views.xml',
        'views/curriculum_views.xml',
        'views/media_curriculum_views.xml',
        'views/subject_mapping_views.xml',
        'views/ptm_meeting_views.xml',
        'views/holiday_views.xml',
        'views/academic_management_menu.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
