# -*- coding: utf-8 -*-

{
    'name': 'RTE Admission',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Digitize RTE Section 12(1)(c) admissions on top of the OpenEduCat admission stack',
    'description': """
        RTE Admission
        ==========================
        - Extends op.admission, op.course and op.parent (no parallel
          models) to capture RTE Section 12(1)(c) applicant details:
          category, income/category certificates, school preferences and
          document verification.
        - Document verification workflow on the admission with a
          dedicated RTE status bar (Draft -> Document Verified/Rejected ->
          Lottery Pending -> Allotted/Waitlisted -> Confirmed -> Admitted
          / Lapsed), driven by chatter-logged action buttons.
        - Seeded, auditable lottery batches per course/academic year that
          hash and shuffle applicants deterministically and publish
          selected/waitlisted results.
        - Reimbursement claim tracking per course/academic year with a
          draft/submitted/approved/paid/rejected workflow.
        - Portal self-service application form and application list for
          parents.
        - Cron jobs for waitlist promotion, confirmation deadline
          reminders and document verification SLA alerts.
        - Allotment letter QWeb report.
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'portal',
        'openeducat_admission',
        'openeducat_core',
        'openeducat_parent',
    ],
    'data': [
        'security/rte_security.xml',
        'security/ir.model.access.csv',
        'data/rte_sequence_data.xml',
        'data/rte_mail_template_data.xml',
        'data/rte_cron_data.xml',
        'views/res_config_settings_views.xml',
        'views/op_admission_views.xml',
        'views/op_course_views.xml',
        'views/rte_lottery_views.xml',
        'views/rte_reimbursement_views.xml',
        'views/rte_class_enrollment_stat_views.xml',
        'views/rte_grievance_views.xml',
        'views/portal_templates.xml',
        'wizard/rte_document_verify_wizard_views.xml',
        'wizard/rte_lottery_wizard_views.xml',
        'views/rte_menus.xml',
        'report/rte_allotment_letter.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
