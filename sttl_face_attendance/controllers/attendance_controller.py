# -*- coding: utf-8 -*-

import time
from collections import defaultdict, deque

from odoo import http
from odoo.http import request

# Per-process sliding-window limiter: this route hands back every
# employee's face photo for a company from one shared secret (the same
# attendance_kiosk_key core hr_attendance already uses for its other
# public kiosk routes), so a leaked/guessed key shouldn't also let an
# attacker script unlimited bulk scraping of the whole roster. Not a
# substitute for keeping the kiosk key secret, and each worker process
# tracks its own window in a multi-worker deployment - put a real rate
# limit at the reverse-proxy layer for a hard guarantee.
_IMAGES_RATE_WINDOW = 60
_IMAGES_RATE_MAX = 10
_images_attempts = defaultdict(deque)


def _images_rate_limited(key):
    now = time.monotonic()
    bucket = _images_attempts[key]
    while bucket and now - bucket[0] > _IMAGES_RATE_WINDOW:
        bucket.popleft()
    if len(bucket) >= _IMAGES_RATE_MAX:
        return True
    bucket.append(now)
    return False


class HrAttendance(http.Controller):

    def _get_kiosk_company(self, token):
        """Same shared-secret pattern hr_attendance itself uses for every
        other public kiosk route: the token is the company's
        attendance_kiosk_key, so an anonymous caller without it gets nothing.
        """
        return request.env['res.company'].sudo().search([('attendance_kiosk_key', '=', token)], limit=1)

    @http.route('/employee/images', type="jsonrpc", auth="public")
    def get_employee_images(self, token, employee_id=None):
        if _images_rate_limited(request.httprequest.remote_addr):
            return []
        company = self._get_kiosk_company(token)
        if not company:
            return []
        domain = [('company_id', '=', company.id)]
        if employee_id:
            domain.append(('id', '=', employee_id))
        employees = request.env['hr.employee'].sudo().search(domain)
        return [{"employee_id": employee.id, "image": employee.image_1920} for employee in employees]
