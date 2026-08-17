{
    'name': 'School Canteen Management',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Prepaid-wallet Cafeteria/Canteen ordering for Students and Teachers',
    'description': """
        School Canteen Management
        ==========================
        - Prepaid wallet per Student/Teacher (top-up cash/online, real-time debit on order)
        - Lightweight menu built on product.template (no stock dependency)
        - Kitchen Display order workflow (draft -> confirmed -> preparing -> ready -> served)
        - Wallet passbook / ledger with full audit trail
        - Daily Sales and Wallet Statement reports
        - Self-service balance check for students/teachers
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
        'security/canteen_groups.xml',
        'security/canteen_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/product_category_data.xml',
        'views/product_template_canteen_views.xml',
        'views/canteen_wallet_views.xml',
        'views/canteen_wallet_transaction_views.xml',
        'views/canteen_order_views.xml',
        'wizard/canteen_wallet_topup_wizard.xml',
        'wizard/canteen_sales_report_wizard.xml',
        'wizard/canteen_wallet_statement_wizard.xml',
        'reports/canteen_sales_report.xml',
        'reports/canteen_wallet_statement_report.xml',
        'views/student_canteen_views.xml',
        'views/faculty_canteen_views.xml',
        'views/canteen_menu.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
