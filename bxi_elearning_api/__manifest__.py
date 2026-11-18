# -*- coding: utf-8 -*-

{
    'name': 'Orbix eLearning API',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Orbix app API for eLearning courses organised by class and section',
    'description': """
        Orbix eLearning API
        ===================
        Backend-only, consumed via the Orbix API layer (bxi_api). Lets the
        app list the eLearning classes and sections (bxi_elearning_class_section),
        browse the courses (website_slides) the signed-in user may see, join
        an open course, open its lessons and mark them completed.

        Kept out of bxi_api_support so schools that don't use eLearning
        don't have to install the website eLearning app.
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'bxi_api',
        'bxi_elearning_class_section',
    ],
    'data': [],
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
