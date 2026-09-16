# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.addons.bxi_student_portal.controllers.student_portal import StudentPortal
from odoo.http import request


class ParentPortal(StudentPortal):

    def _portal_children(self):
        user = request.env.user
        if not user.child_ids:
            return request.env['op.student'].sudo()
        return request.env['op.student'].sudo().search([('user_id', 'in', user.child_ids.ids)])

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        children = self._portal_children()
        if children:
            values['portal_children'] = children
        return values

    @http.route(['/my/child'], type='http', auth='user', website=True)
    def portal_children_list(self, **kw):
        children = self._portal_children()
        if len(children) == 1:
            return request.redirect('/my/academics/%d' % children.id)
        return request.render('bxi_parent_portal.portal_children_list', {
            'children': children,
            'attendance_by_student': {s.id: self._attendance_summary(s) for s in children},
            'fees_due_by_student': {s.id: self._fees_due_total(s) for s in children},
            'page_name': 'children',
        })
