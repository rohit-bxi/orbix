{
    'name': 'Certificate Management',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Configure, issue, print and verify student certificates',
    'description': """
        Standalone module integrating with OpenEduCat to manage:
        - Configurable certificate types (transfer, completion, achievement, etc.)
          with per-type numbering and optional custom wording, no coding required
        - Draft -> Generated -> Issued -> Revoked / Expired workflow with approvals
        - Single and bulk (batch/course-wide) certificate issuance
        - Printable QWeb PDF certificates with an embedded QR verification code
        - Public certificate verification page
        - Student portal access to their own certificates
        - Automatic expiry tracking and reminder emails
        """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'portal',
        'website',
        'openeducat_core',
    ],
    'data': [
        'security/certificate_security.xml',
        'security/certificate_rules.xml',
        'security/ir.model.access.csv',
        'data/certificate_cron.xml',
        'data/certificate_mail_template.xml',
        'data/certificate_type_data.xml',
        'wizard/certificate_bulk_wizard_view.xml',
        'wizard/certificate_revoke_wizard_view.xml',
        'report/certificate_report.xml',
        'report/certificate_template.xml',
        'views/certificate_type_views.xml',
        'views/certificate_views.xml',
        'views/student_views.xml',
        'views/faculty_views.xml',
        'views/certificate_menu.xml',
        'controllers/certificate_portal_templates.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
