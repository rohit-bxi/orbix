# -*- coding: utf-8 -*-

{
    'name': 'Academic Management Dashboard',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Unified curriculum, lesson plan and academic calendar overview',
    'description': """
        Academic Management Dashboard
        ==============================
        A single overview screen, placed before Curriculum in the Academic
        Management menu, that pulls live KPIs and a curriculum board from
        the modules already installed: Curriculum, Subject Mapping, Smart
        Books and Parent-Teacher Meetings (bxi_academic_management), and
        Lesson Plans (bxi_lesson_plan).
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'bxi_academic_management',
        'bxi_lesson_plan',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/academic_dashboard_actions.xml',
        'views/academic_dashboard_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bxi_academic_dashboard/static/src/academic_dashboard/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
