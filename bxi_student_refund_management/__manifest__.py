# -*- coding: utf-8 -*-

{
    'name': 'Student Fee Refund Management',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Track and process fee refund requests (overpayment, withdrawal, cancelled services) with an approval workflow',
    'description': """
        Student Fee Refund Management
        ==============================
        - Refund Request: student/parent-linked refund with a live-computed
          Total Fee / Total Paid / Excess / Pending snapshot read from the
          student's real posted invoices (openeducat_fees), an approval
          workflow, a bank-details snapshot, a supporting-document
          checklist and uploads.
        - Tracking-only: approving/processing a refund never creates or
          changes accounting entries. "Processed" means staff paid the
          parent outside Odoo and recorded the UTR/reference back here.
        - Bulk Refund wizard: finds students with excess payment and
          creates one refund request per selected student with a shared
          refund type/method/amount-calculation rule.
        - Guarded delete wizard with a financial/impact preview that
          permanently removes a refund request and its documents.
        - Smart button on the Student form; list/search filterable by
          Class, Section and Status.
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'account',
        'openeducat_core',
        'openeducat_fees',
        'openeducat_parent',
    ],
    'data': [
        'security/refund_groups.xml',
        'security/refund_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/refund_request_views.xml',
        'views/op_student_views.xml',
        'wizard/refund_delete_wizard_views.xml',
        'wizard/refund_bulk_wizard_views.xml',
        'views/refund_menu.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
