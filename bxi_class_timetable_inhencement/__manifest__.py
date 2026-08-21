# -*- coding: utf-8 -*-

{
    'name': 'Class & Timetable Enhancement',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Class Manager (Section/Capacity/Class-Teacher), weekly timetable, teacher workload & reassignment tools',
    'description': """
        Class & Timetable Enhancement
        ==============================
        - Class Manager: create/edit Sections (op.batch) with Capacity, Assign Teacher and Description
        - Timetable: weekly Period x Day schedule per Class/Section, with Lock/Unlock
        - Teacher Workload: weekly period count, limit status and weekday availability on the Teacher form
        - Add / Remove / Transfer Period and Reassign Class wizards
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'openeducat_core',
        'openeducat_classroom',
        'openeducat_timetable',
        'bxi_academic_management',
    ],
    'data': [
        'security/class_timetable_groups.xml',
        'security/ir.model.access.csv',
        'security/class_timetable_security.xml',
        'views/batch_views.xml',
        'views/timing_views.xml',
        'views/timetable_views.xml',
        'wizard/add_period_wizard_views.xml',
        'wizard/remove_period_wizard_views.xml',
        'wizard/transfer_period_wizard_views.xml',
        'wizard/reassign_class_wizard_views.xml',
        'views/faculty_workload_views.xml',
        'views/class_timetable_menu.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
