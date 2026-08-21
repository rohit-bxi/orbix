# -*- coding: utf-8 -*-

{
    'name': 'Fee Management',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Fee structure setup and fee collection screens on top of OpenEduCat Fees',
    'description': """
        Fee Management
        ==============
        - Fee Categories (Configuration master data): the fee heads that make
          up a structure (Tuition, Transport, Library, ...), each linked to
          the accounting product OpenEduCat's invoicing engine already uses.
        - Fee Structures: extends OpenEduCat's Fee Terms with academic year,
          class/section scoping, a flat fee-category breakdown, a payment
          schedule generator, late fee rules, an early-payment discount, and
          a guarded activate/deactivate workflow with an impact preview.
        - Fee Collection: list/kanban screens over the fee lines OpenEduCat
          already creates at admission, with a live paid/pending/overdue
          status, and a payment wizard (built on Odoo's own payment
          registration wizard) to record manual, offline or partial
          payments.
        - Daily cron keeps collection status and late fees current.
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'openeducat_fees',
        'openeducat_admission',
        'account',
        'mail',
    ],
    'data': [
        'security/fee_security.xml',
        'security/ir.model.access.csv',
        'views/fee_category_views.xml',
        'views/fee_structure_views.xml',
        'wizard/fee_payment_wizard_views.xml',
        'wizard/structure_deactivate_wizard_views.xml',
        'views/student_fees_details_views.xml',
        'data/ir_cron_data.xml',
        'views/fee_menu.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
