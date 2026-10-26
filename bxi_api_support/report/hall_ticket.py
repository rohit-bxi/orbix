# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import time

from odoo import api, models


class ReportHallTicketSingle(models.AbstractModel):
    """One student's hall ticket for one exam session. openeducat_exam's
    own report renders every student of the class into a single PDF, which
    can't be handed to a family - this feeds the same template a one-item
    list, built the same way (subject lines via that report's get_subject).
    Render with data={'student_id': <id>} and the session as the record.
    """
    _name = 'report.bxi_api_support.report_hall_ticket_single'
    _description = 'Single-Student Hall Ticket'

    @api.model
    def _get_report_values(self, docids, data=None):
        sessions = self.env['op.exam.session'].browse(docids)
        student = self.env['op.student'].browse((data or {}).get('student_id'))
        stock_report = self.env['report.openeducat_exam.report_ticket']
        tickets = []
        for session in sessions:
            enrollment = student.course_detail_ids.filtered(lambda line: line.course_id == session.course_id)[:1]
            tickets.append({
                'exam': session.name,
                'exam_code': session.exam_code,
                'course': session.course_id.name,
                'student': student.name,
                'image': student.image_1920,
                'roll_number': enrollment.roll_number,
                'line': stock_report.get_subject(session),
            })
        return {
            'doc_ids': sessions.ids,
            'doc_model': 'op.exam.session',
            'docs': sessions,
            'time': time,
            'get_data': tickets,
        }
