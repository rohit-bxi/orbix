# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

{
    'name': 'Assessments & Exams',
    'version': '19.0.2.0.0',
    'category': 'Education',
    'summary': 'Digital exam authoring, AI-generated assignments and auto-grading for teachers',
    'description': """
        Assessments & Exams
        ====================
        - Digital Exam Management: teachers author exams made of short answer, long
          answer and multiple choice questions. Each question carries its own marks
          and, for short/long answer questions, a sample answer/keyword reference
          that will be used later to auto-grade student responses. An exam can
          optionally be linked back to a Curriculum.
        - MCQ questions are authored with answer options and exactly one option
          marked correct.
        - Question import from Excel (structured) or Word/PDF (a documented
          plain-text block format).
        - Export/print a question paper as a PDF from the exam form.
        - AI Assignment: generate a set of exam questions from class/subject/topic/
          difficulty using Anthropic's API, then review/edit/regenerate before use.
        - Assign Assessment: schedule a published exam to a class/teacher/date-time,
          seeding one submission per selected student.
        - Auto-Grading & Submissions: MCQ answers are scored instantly; short/long
          answers are graded by AI against the question's sample answer/keywords.
          Submissions can be manually re-evaluated with a logged marks adjustment
          and reason.
        - Dashboard: KPIs, alerts and a Recent Exams / Performance by Class overview,
          scoped by the same rules as everywhere else (teachers see their own exams,
          coordinators/managers see all).
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'base',
        'mail',
        'openeducat_core',
        'bxi_academic_management',
    ],
    'data': [
        'security/assessment_hub_security.xml',
        'security/ir.model.access.csv',
        'report/exam_question_paper_report.xml',
        'report/exam_question_paper_template.xml',
        'views/res_config_settings_views.xml',
        'wizard/exam_question_import_wizard_views.xml',
        'wizard/ai_assignment_generate_wizard_views.xml',
        'wizard/assessment_reevaluation_wizard_views.xml',
        'wizard/assessment_autograde_wizard_views.xml',
        'views/exam_question_views.xml',
        'views/assessment_submission_views.xml',
        'views/assessment_session_views.xml',
        'views/exam_views.xml',
        'views/assessment_dashboard_actions.xml',
        'views/exam_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bxi_assessment_hub/static/src/assessment_dashboard/**/*',
        ],
    },
    'external_dependencies': {
        'python': ['openpyxl', 'python-docx', 'PyPDF2'],
    },
    'installable': True,
    'application': True,
    'license': 'OPL-1',
}
