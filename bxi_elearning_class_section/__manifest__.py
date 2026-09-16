# -*- coding: utf-8 -*-

{
    'name': 'eLearning Class & Section',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Organize eLearning courses by Class and Section, in the backend and on the website',
    'description': """
        eLearning Class & Section
        ==========================
        - Class / Section: master data for organizing eLearning Courses
        - Course: assign a Class and Section (section list restricted to the selected Class)
        - Website: filter and browse the course listing by Class and Section
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'website_slides',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/elearning_class_section_views.xml',
        'views/slide_channel_views.xml',
        'views/website_slides_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
