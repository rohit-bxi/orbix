# -*- coding: utf-8 -*-

{
    'name': 'School Announcements',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Compose and broadcast school announcements to students, teachers and parents',
    'description': """
        School Announcements
        =====================
        - Compose an announcement with a category, priority, message body,
          target audience (all students / all teachers / all parents / a
          specific class / everyone) and delivery channels (in-app, email,
          SMS, push).
        - Publish immediately or schedule for a later date; a cron picks up
          due scheduled announcements.
        - Recipient count is resolved and snapshotted from the target
          audience at publish time.
        - In-app delivery logs a message on the announcement (visible via
          chatter/follower notifications); email delivery uses a mail
          template. SMS and push are accepted as delivery-channel choices
          but not yet wired to a live provider/mobile app.
    """,
    'author': 'Vijay Shanker Dubey',
    'depends': [
        'base',
        'mail',
        'openeducat_core',
        'openeducat_parent',
    ],
    'data': [
        'security/announcement_groups.xml',
        'security/announcement_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/mail_template_data.xml',
        'views/announcement_views.xml',
        'views/announcement_menu.xml',
        'data/ir_cron_data.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
