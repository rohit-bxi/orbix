# -*- coding: utf-8 -*-
{
    'name': 'Orbix Student Learning',
    'version': '19.0.1.1.0',
    'category': 'Education',
    'summary': 'Study notes, doubts, reading progress, career guidance, student community, school info '
               'and the online admission application behind the Orbix student app',
    'description': """
        Orbix Student Learning
        ======================
        The data behind the Orbix student app screens (the API lives in
        bxi_api_support):

        - Study notes teachers publish per subject and class, with
          comments, bookmarks and a PDF copy.
        - Doubts students ask their subject teacher ("Smart Doubt Buddy").
        - Reading progress and a reading list for the digital library.
        - Career guidance from the student's own subject results, by
          school-editable career rules (no external AI).
        - A student community per section, with teacher moderation and
          reporting.
        - Extra homework details (chapter, difficulty, objectives,
          requirements).
        - The school's "About" page content (mission, values, team).
        - The online admission application: steps, typed documents and a
          personal statement on top of OpenEduCat admissions.
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'base',
        'mail',
        'openeducat_core',
        'openeducat_assignment',
        'openeducat_library',
        'openeducat_admission',
        'openeducat_exam',
        'bxi_academic_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/student_learning_security.xml',
        'data/career_data.xml',
        'data/career_usage_data.xml',
        'report/study_note_report.xml',
        'views/study_note_views.xml',
        'views/doubt_views.xml',
        'views/community_views.xml',
        'views/career_views.xml',
        'views/school_info_views.xml',
        'views/assignment_views.xml',
        'views/admission_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
