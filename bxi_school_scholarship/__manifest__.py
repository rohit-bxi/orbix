# -*- coding: utf-8 -*-

{
    'name': 'School Scholarship Management',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Assign, track and report scholarships awarded to students against their fee structure',
    'description': """
        School Scholarship Management
        ==============================
        - Scholarship Programs (Configuration master data): named scholarships
          per type (Merit, Need-Based, Sports, Academic Excellence, ...) with
          default coverage settings.
        - Student Scholarship: assign a scholarship to a student with
          coverage (percentage or fixed amount, optionally capped), a staff
          entered fee breakdown snapshot, a validity period, an approval
          workflow, a supporting-document checklist and uploads.
        - Fee breakdown is a snapshot entered on the scholarship record
          itself (not a live read of the invoicing engine), so it never
          touches real invoices/accounting.
        - Guarded removal wizard showing the financial impact before
          archiving a scholarship.
        - Printable scholarship report (PDF).
        - Smart button on the Student form; list/search filterable by
          Class, Section, Scholarship and Approval Status.
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'product',
        'openeducat_core',
        'openeducat_fees',
    ],
    'data': [
        'security/scholarship_groups.xml',
        'security/scholarship_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/scholarship_program_views.xml',
        'views/student_scholarship_views.xml',
        'views/op_student_views.xml',
        'wizard/scholarship_remove_wizard_views.xml',
        'report/scholarship_report.xml',
        'report/scholarship_report_template.xml',
        'views/scholarship_menu.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
