# -*- coding: utf-8 -*-

{
    'name': 'Fees Dashboard',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Unified fees dashboard: collection, refunds, scholarships, exemptions and online payments at a glance',
    'description': """
        Fees Dashboard
        ==============
        A single overview screen, placed before Fee Collection in the Fee
        Management menu, that pulls live KPIs and charts from every fees
        module already installed: Fee Collection (bxi_fee_management),
        Refunds (bxi_student_refund_management), Scholarships
        (bxi_school_scholarship), Fee Exemptions
        (bxi_fee_exemption_management) and the Online Payment Gateway
        (bxi_online_fee_payment).

        Also adds a Payment Report (pivot/graph), a per fee-line Receipt
        Generator report, and quick-action shortcuts into each module's
        create screens.
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'bxi_fee_management',
        'bxi_school_scholarship',
        'bxi_student_refund_management',
        'bxi_fee_exemption_management',
        'bxi_online_fee_payment',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/fee_dashboard_actions.xml',
        'views/fee_receipt_report.xml',
        'views/fee_dashboard_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bxi_fee_dashboard/static/src/fee_dashboard/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
