# -*- coding: utf-8 -*-

{
    'name': 'Student Attendance',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Student check-in/out on the standard Attendances kiosk, filterable by Student/Class/Section/Date',
    'description': """
        Student Attendance
        ===================
        - Every student gets a lightweight shadow hr.employee record, so
          the standard Attendances kiosk/systray/badge check-in/out flow
          works for students exactly as it does for staff.
        - hr.attendance gains Student/Class/Section (derived from the
          shadow employee and the student's running enrollment) and a
          Present/Absent/Late/Excused status for teacher-entered
          corrections, alongside Period (op.session).
        - Generates op.session periods for a date from the weekly
          bxi.timetable.line schedule, so period-scoped attendance has
          something to attach to.
        - Student Attendance list/search filterable by Student, Class,
          Section and Date.
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'hr',
        'hr_attendance',
        'openeducat_core',
        'openeducat_timetable',
        'bxi_class_timetable_inhencement',
    ],
    'data': [
        'security/student_attendance_security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/hr_attendance_views.xml',
        'views/student_attendance_menu.xml',
    ],
    'post_init_hook': '_create_student_employees',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
