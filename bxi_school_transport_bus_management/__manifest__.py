{
    'name': 'School Transport / Bus Management',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Bus routes, stops, student transport registration and fee billing built on Fleet',
    'description': """
        School Transport / Bus Management
        ==================================
        - Built on Odoo Fleet: school buses are fleet.vehicle records, reusing its
          documents, contracts (permits/insurance/PUC/fitness), services and odometer
        - Bus routes with ordered stops, pickup/drop timings and per-stop fees
        - Student transport registration with seat-capacity checks and fee invoicing
        - Driver profile with license tracking and expiry reminders
        - Bulk registration wizard by batch
        - Route manifest report for drivers
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'hr',
        'fleet',
        'account',
        'openeducat_core',
    ],
    'data': [
        'security/transport_groups.xml',
        'security/transport_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/product_data.xml',
        'data/ir_cron_data.xml',
        'views/fleet_vehicle_transport_views.xml',
        'views/transport_driver_views.xml',
        'views/transport_route_views.xml',
        'views/transport_registration_views.xml',
        'views/student_transport_views.xml',
        'wizard/transport_bulk_registration_wizard.xml',
        'reports/transport_route_manifest_report.xml',
        'views/transport_menu.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
