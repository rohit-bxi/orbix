{
    'name': 'Student Lab Management',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Manage lab rooms, sessions, attendance, experiments and equipment issue for OpenEduCat',
    'description': """
        Student Lab Management
        =======================
        Standalone module integrating with OpenEduCat to manage:
        - Lab Rooms & Equipment (master data)
        - Lab Session Scheduling (with hard-block conflict validation)
        - Auto-generated Attendance on session confirmation
        - Experiments & Results
        - Simple Equipment Issue/Return log (no stock integration)
        """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'openeducat_core',
    ],
    'data': [
        'security/lab_security.xml',
        'security/ir.model.access.csv',
        'data/lab_sequence.xml',
        'views/lab_room_views.xml',
        'views/lab_equipment_views.xml',
        'views/lab_session_views.xml',
        'views/lab_attendance_views.xml',
        'views/lab_experiment_views.xml',
        'views/lab_equipment_issue_views.xml',
        'views/lab_menu.xml',
        'report/lab_attendance_sheet_report.xml',
        'report/lab_utilization_report.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
