# -*- coding: utf-8 -*-

{
    'name': 'Orbix System Logs API',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Curated, admin-only "who changed what" audit read API over existing mail.tracking.value data',
    'description': """
        Orbix System Logs API
        =========================
        Backend-only, consumed via the Orbix API layer (bxi_api). Odoo
        already tracks field changes via `tracking=True` on the models
        that matter across this project (fee exemption/refund status,
        identity verification status, etc.) - this module adds no new
        capture mechanism, only a curated, filterable, admin-only read
        endpoint over that existing `mail.tracking.value` data, gated
        behind `base.group_system` (full administration access).
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'bxi_api',
    ],
    'data': [],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
