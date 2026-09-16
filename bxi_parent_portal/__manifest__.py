{
    'name': 'BXI Parent Portal',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': "Web portal for parents to view their children's academic record",
    'description': """
        Adds a "My Children" area under /my for a logged-in parent (portal
        user), listing every child linked via res.users.child_ids and
        reusing bxi_student_portal's /my/academics pages for each child's
        attendance, timetable, exams, assignments, library and fees -
        no duplicated views, the same ir.rule (self or child) already
        enforces the scoping.
        """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'bxi_student_portal',
        'openeducat_parent',
    ],
    'data': [
        'views/parent_portal_templates.xml',
    ],
    'post_init_hook': 'set_parent_portal_partner_rule',
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
