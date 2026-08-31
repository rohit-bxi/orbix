# -*- coding: utf-8 -*-

{
    'name': 'Orbix Library Book Requests',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Draft/pending/approved/rejected book request workflow on top of openeducat_library, via the Orbix API',
    'description': """
        Orbix Library Book Requests
        ==============================
        Backend-only, consumed via the Orbix API layer (bxi_api).
        `openeducat_library` already has `media.queue`, a simple
        reservation queue, but nothing modeling a request that a librarian
        explicitly approves or rejects (the Figma design shows distinct
        Pending / Approved / Rejected screens). This module adds that
        status-driven workflow as its own lightweight model, without
        touching the existing reservation/issue engine.

        Same status + readonly-on-terminal-state pattern used earlier this
        project for fee exemptions and refunds: explicit per-field
        `readonly="status in (...)"`, since container-level readonly does
        not cascade in this Odoo 19 build.
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'bxi_api',
        'openeducat_library',
        'openeducat_core',
    ],
    'data': [
        'security/book_request_groups.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/book_request_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
