{
    'name': 'BXI Student Portal',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Self-service web portal for students to view their own academic record',
    'description': """
        Gives a logged-in student (portal user) a "My Academics" area under
        /my with their own:
        - Profile (course, batch, roll number)
        - Attendance history and percentage
        - Weekly timetable
        - Exam results / marksheets
        - Assignments and submission status
        - Library issue/return history
        - Fee payment history

        Every page is scoped to the logged-in student via ir.rule (never a
        controller-level check alone). Routes accept an optional student_id
        so bxi_parent_portal can reuse the same pages for a parent viewing
        one of their children.
        """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'portal',
        'website',
        'openeducat_core',
        'openeducat_parent',
        'openeducat_attendance',
        'openeducat_timetable',
        'openeducat_exam',
        'openeducat_assignment',
        'openeducat_library',
        'openeducat_fees',
    ],
    'data': [
        'security/student_portal_security.xml',
        'security/ir.model.access.csv',
        'views/student_portal_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
