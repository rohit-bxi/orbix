# -*- coding: utf-8 -*-

{
    'name': 'Orbix People Management',
    'version': '19.0.1.4.0',
    'category': 'Education',
    'summary': 'Teacher profile, assignment and workload details for the user-management screens',
    'description': """
        Orbix People Management
        =======================
        The data behind the office's Teacher / Student / Parent create and
        update screens that the core records lack:

        - Teacher: Teacher ID (T-0001... sequence), emergency-contact relation, certifications, notes,
          assigned classes and sections, timetable auto-assign flag,
          designation (HR Job Position), other responsibilities and
          employment status.
        - Teacher lesson & evaluation permissions (lesson plans, homework,
          evaluation, exam marks, reports) - enforced by the app API.
        - Teacher documents: Aadhaar card, CV, certificates.
        - Staff responsibilities: a simple tag list.
        - Student: current class, section, department and enrolment status
          (read-only, from the running enrolment), and the Draft flag of
          students saved with the app's "Save Draft".
        - Parent: status, and department / class from the children.

        The REST endpoints that use these fields live in bxi_api_support.
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'base',
        'hr',
        'openeducat_core',
        'openeducat_parent',
        'bxi_class_timetable_inhencement',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/people_management_security.xml',
        'data/teacher_code_sequence.xml',
        'views/staff_responsibility_views.xml',
        'views/op_faculty_views.xml',
        'views/op_student_parent_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
