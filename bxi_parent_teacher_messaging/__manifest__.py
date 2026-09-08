# -*- coding: utf-8 -*-

{
    'name': 'Orbix Parent-Teacher Messaging',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Direct messaging between a parent and a teacher about a specific student, via the Orbix API',
    'description': """
        Orbix Parent-Teacher Messaging
        =================================
        Backend-only messaging, consumed via the Orbix API layer
        (bxi_api). A thread is always scoped to one parent, one teacher,
        and one student - there is no group chat and no unscoped direct
        messaging between arbitrary users, matching the one feature the
        Figma design actually specifies ("Parent-Teacher Communication").

        Endpoints:
        - list my threads (parent or teacher side)
        - start a thread
        - list/send messages in a thread
        - mark a thread read

        A small backend list/form view is included for staff visibility
        (e.g. a school admin auditing conversations), not as a chat UI to
        build against - the mobile app owns that.
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'base',
        'mail',
        'bxi_api',
        'openeducat_core',
        'openeducat_parent',
        'bxi_academic_management',
    ],
    'data': [
        'security/messaging_groups.xml',
        'security/ir.model.access.csv',
        'views/message_thread_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
