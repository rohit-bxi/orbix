{
    'name': 'Lesson Plan',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Teacher lesson plan authoring and Academic Coordinator/Manager approval workflow',
    'description': """
        Lesson Plan
        ============
        - Teachers submit lesson plans (objective, activities, resources, recall questions,
          class work, home work, teaching aids, remarks) for a Class/Subject/Quarter
        - Academic Coordinator/Manager reviews and Approves or Requests Revision, with feedback
        - Full audit trail via chatter
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'openeducat_core',
        'bxi_academic_management',
    ],
    'data': [
        'security/lesson_plan_security.xml',
        'security/ir.model.access.csv',
        'wizard/lesson_plan_review_wizard_views.xml',
        'views/lesson_plan_views.xml',
        'views/lesson_plan_menu.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
