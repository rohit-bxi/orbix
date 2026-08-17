{
    'name': 'Health Center',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Health & Medical Records management for Students and Teachers',
    'description': """
        Health Center
        =============
        Standalone module integrating with OpenEduCat to manage:
        - Structured medical profile on Student and Teacher records
        - Clinic / infirmary visit log with a state workflow
        - Vaccination and immunization tracking
        - Periodic health checkups (BMI, vision, dental, fitness)
        - Health Staff (Nurse/Doctor) registry with dedicated access control
        - Reporting dashboard and printable medical certificates
        """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'hr',
        'openeducat_core',
    ],
    'data': [
        'security/op_health_center_groups.xml',
        'security/op_health_center_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'views/health_vaccine_type_views.xml',
        'views/health_visit_views.xml',
        'views/health_vaccination_views.xml',
        'views/health_checkup_views.xml',
        'views/student_health_views.xml',
        'views/faculty_health_views.xml',
        'views/health_dashboard_views.xml',
        'wizard/health_certificate_wizard.xml',
        'wizard/health_visit_report_wizard.xml',
        'reports/health_certificate_report.xml',
        'reports/health_certificate_template.xml',
        'reports/health_visit_report.xml',
        'views/health_menu.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
