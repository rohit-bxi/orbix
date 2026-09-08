# -*- coding: utf-8 -*-

{
    'name': 'Fee Exemption Management',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Review, approve and track fee exemption requests against a student\'s fee structure',
    'description': """
        Fee Exemption Management
        ==========================
        - Exemption Request: student/parent-linked request (financial
          hardship, merit, sibling discount, sports quota, staff dependent,
          special category, ...) with a live-computed Total Fee / Paid /
          Pending snapshot read from the student's real posted invoices
          (openeducat_fees), a supporting-document checklist and uploads.
        - Approve Request wizard: configure approval type, exemption method
          (percentage/fixed amount), scope of fee categories, validity
          period and notification settings; confirming creates the granted
          Fee Exemption record.
        - Reject Request wizard: reason category, a detailed reason sent to
          the parent, optional reapplication suggestions, and a typed
          confirmation guard.
        - Fee Exemption: the granted benefit, with a staff-entered fee
          category breakdown snapshot, eligibility criteria, validity
          period and its own draft/approve/reject workflow for exemptions
          created directly by staff (bypassing a parent request).
        - Tracking-only: approving, editing or deleting an exemption never
          creates or changes accounting entries or invoices.
        - Guarded delete wizard with a financial impact preview.
        - Smart buttons on the Student form; list/search filterable by
          Class, Section and Status.
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'base',
        'mail',
        'product',
        'openeducat_core',
        'openeducat_fees',
        'openeducat_parent',
        'bxi_student_refund_management',
        'bxi_fee_management',
    ],
    'data': [
        'security/exemption_groups.xml',
        'security/exemption_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/fee_exemption_request_views.xml',
        'views/fee_exemption_views.xml',
        'views/op_student_views.xml',
        'wizard/exemption_approve_wizard_views.xml',
        'wizard/exemption_reject_wizard_views.xml',
        'wizard/exemption_delete_wizard_views.xml',
        'views/exemption_menu.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
