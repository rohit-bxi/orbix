{
    'name': 'School Event Management',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'School-specific events on top of the standard Event app',
    'description': """
        Enhances Odoo's standard Event app for school use:
        - Event categories (Sports Day, Annual Day, PTM, Workshop, Field Trip,
          Open House, Competition) with seed event.type templates
        - Venue catalog with double-booking prevention
        - Academic year/term context and class/batch/audience targeting
        - Bulk registration of a whole class/batch
        - Fee-bearing event invoicing (account.move, same pattern as
          transport registration)
        - Field trip permission slips and transport add-on
        - Bulk participation-certificate issuance for attendees
        - Announcement bridge and portal RSVP for parents/students
        """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'event',
        'mail',
        'portal',
        'openeducat_core',
        'openeducat_parent',
        'bxi_certificate_management',
        'bxi_school_announcement',
        'bxi_school_transport_bus_management',
    ],
    'data': [
        'security/event_security.xml',
        'security/event_rules.xml',
        'security/ir.model.access.csv',
        'data/event_type_data.xml',
        'wizard/event_bulk_registration_wizard_view.xml',
        'views/event_venue_views.xml',
        'views/event_event_views.xml',
        'views/event_registration_views.xml',
        'views/student_views.xml',
        'views/faculty_views.xml',
        'views/parent_views.xml',
        'views/ptm_meeting_views.xml',
        'views/event_menu.xml',
        'controllers/event_portal_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
