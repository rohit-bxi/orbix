# -*- coding: utf-8 -*-

{
    'name': 'School Uniform Management',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Uniform catalog, stock, ordering, invoicing and issue tracking for Students and Teachers',
    'description': """
        School Uniform Management
        ==========================
        - Uniform catalog built on product.template (Size/Color as product variants)
        - Lightweight built-in stock ledger per item/size (no stock app dependency)
        - Uniform Policy: required uniform set per Course/Gender/Season, auto-loaded onto orders
        - Uniform Order for Students/Teachers with invoicing (reuses account.move)
        - Issue workflow that debits stock, with manager override for out-of-stock issue
        - Size Exchange wizard (return old size, issue new size)
        - Low-stock and issued-register visibility from list/kanban views
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'hr',
        'product',
        'account',
        'openeducat_core',
    ],
    'data': [
        'security/uniform_groups.xml',
        'security/uniform_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/product_category_data.xml',
        'data/product_attribute_data.xml',
        'views/product_template_uniform_views.xml',
        'views/uniform_stock_views.xml',
        'views/uniform_policy_views.xml',
        'views/uniform_order_views.xml',
        'wizard/uniform_exchange_wizard_views.xml',
        'views/student_uniform_views.xml',
        'views/faculty_uniform_views.xml',
        'views/uniform_menu.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
