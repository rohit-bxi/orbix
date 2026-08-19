# -*- coding: utf-8 -*-

{
    'name': 'Academic Management',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Curriculum boards, class assignment, smart books and subject-teacher mapping',
    'description': """
        Academic Management
        ====================
        - Curriculum: define curriculum boards (e.g. CBSE, ICSE, State Board) and assign Classes to them
        - Smart Book: curriculum-linked books, built on the existing Library media model
        - Subject Mapping: map Subject + Class + Curriculum to a Teacher
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'openeducat_core',
        'openeducat_library',
    ],
    'data': [
        'security/academic_management_groups.xml',
        'security/ir.model.access.csv',
        'views/board_views.xml',
        'views/curriculum_views.xml',
        'views/media_curriculum_views.xml',
        'views/subject_mapping_views.xml',
        'views/academic_management_menu.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
