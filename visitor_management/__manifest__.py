# -*- coding: utf-8 -*-
#############################################################################
#
#    Hundred Solutions
#
#    Copyright (C) 2023-TODAY Hundred Solutions AS(<https://www.hundredsolutions.com/>)
#    Author: Arjun Baidya (arjun.b@hundredsolutions.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################

{
    'name': 'Visitor Management System',
    'version': '19.0.1.0.0',
    'summary': """Manage your visitor by smart app""",
    'author': "Hundred Solutions",
    'maintainer': 'Hundred Solutions',
    'company': "Hundred Solutions",
    'website': 'https://www.hundredsolutions.com/',
    'category': 'Industries',
    'description': """
    Helps You To Manage visitor for your company.
    """,
    'depends': [
        'base',
        'hr',
        'contacts',
        'mail',
    ],
    'data': [
        'security/security_group.xml',
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'data/mail_template.xml',
        'views/visit.xml',
        'views/visitor.xml',
        'wizard/visitor_report_wizard.xml',
        'reports/report.xml',
        "reports/daily_visitor_report.xml"

    ],
    'images': ['static/description/banner.png'],
    'license': 'AGPL-3',
    'installable': True,
    'application': True,
}
