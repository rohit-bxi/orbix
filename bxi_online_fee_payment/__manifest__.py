# -*- coding: utf-8 -*-

{
    'name': 'Orbix Online Fee Payment',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Razorpay backend integration for parent fee payments via the Orbix mobile app',
    'description': """
        Orbix Online Fee Payment
        ==========================
        Backend-only Razorpay integration, consumed via the Orbix API
        layer (bxi_api). The mobile app owns the checkout UI and the
        Razorpay SDK - Odoo only:

        - Returns a student's live fee/payment summary
          (reuses bxi_student_refund_management's get_fee_payment_summary()).
        - Creates a Razorpay order for a specific fee line.
        - Verifies the client-reported payment signature and/or the
          Razorpay webhook, then reconciles it as a real payment against
          the invoice using bxi_fee_management's existing payment-register
          flow (bxi.fee.payment.wizard) - no separate ledger is invented.
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'base',
        'bxi_api',
        'bxi_fee_management',
        'bxi_student_refund_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/payment_order_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
