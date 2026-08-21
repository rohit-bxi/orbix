# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request


class HrAttendance(http.Controller):

    def _get_kiosk_company(self, token):
        """Same shared-secret pattern hr_attendance itself uses for every
        other public kiosk route: the token is the company's
        attendance_kiosk_key, so an anonymous caller without it gets nothing.
        """
        return request.env['res.company'].sudo().search([('attendance_kiosk_key', '=', token)], limit=1)

    @http.route('/employee/images', type="jsonrpc", auth="public")
    def get_employee_images(self, token, employee_id=None):
        company = self._get_kiosk_company(token)
        if not company:
            return []
        domain = [('company_id', '=', company.id)]
        if employee_id:
            domain.append(('id', '=', employee_id))
        employees = request.env['hr.employee'].sudo().search(domain)
        return [{"employee_id": employee.id, "image": employee.image_1920} for employee in employees]
