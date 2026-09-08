# -*- coding: utf-8 -*-

{
    'name': 'Orbix Settings API',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Single admin read/write API surface over existing Orbix module settings',
    'description': """
        Orbix Settings API
        ======================
        Backend-only, consumed via the Orbix API layer (bxi_api). No new
        Odoo UI screen - the mobile app renders the settings form. This
        module is a curated, allow-listed read/write surface over the
        `ir.config_parameter`-backed settings that already exist:

        - Notifications: bxi_notification_gateway's MSG91 credentials
        - Finance: bxi_online_fee_payment's Razorpay credentials and
          default payment journal

        Secret values (API keys/secrets) are never returned in full over
        the API - only whether they are configured - the same way a
        password field never round-trips its value back to a client.

        Appearance, Parent, Teacher, Staff and Online-School settings from
        the Figma design have no concrete backing fields yet in this
        codebase and are intentionally not fabricated here; they can be
        added to the same allow-list once those fields exist.
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'base',
        'bxi_api',
        'bxi_notification_gateway',
        'bxi_online_fee_payment',
    ],
    'data': [],
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
