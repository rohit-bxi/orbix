from odoo import http
from odoo.http import request


class SchoolEventPortal(http.Controller):

    def _portal_students(self):
        user = request.env.user
        students = request.env['op.student'].sudo().search([('user_id', '=', user.id)])
        if user.child_ids:
            students |= request.env['op.student'].sudo().search([('user_id', 'in', user.child_ids.ids)])
        return students

    @http.route('/my/events', type='http', auth='user', website=True)
    def portal_my_events(self, **kw):
        students = self._portal_students()
        # Events the household is eligible for: whole-school audiences, or
        # specific_class events targeting one of the students' classes.
        course_ids = students.mapped('course_detail_ids.course_id').ids
        batch_ids = students.mapped('course_detail_ids.batch_id').ids
        domain = ['|', '|',
                  ('target_audience', 'in', ('all_students', 'all_parents', 'everyone')),
                  '&', ('target_audience', '=', 'specific_class'), ('course_ids', 'in', course_ids or [0]),
                  '&', ('target_audience', '=', 'specific_class'), ('batch_ids', 'in', batch_ids or [0])]
        events = request.env['event.event'].sudo().search(domain, order='date_begin')
        registrations = request.env['event.registration'].sudo().search([
            ('student_id', 'in', students.ids),
        ])
        registration_by_event = {}
        for reg in registrations:
            registration_by_event.setdefault(reg.event_id.id, reg)
        return request.render('bxi_school_event_management.portal_my_events', {
            'events': events,
            'students': students,
            'registration_by_event': registration_by_event,
            'page_name': 'event',
        })

    @http.route('/my/events/<int:event_id>/rsvp', type='http', auth='user', website=True, methods=['POST'])
    def portal_event_rsvp(self, event_id, student_id, **kw):
        students = self._portal_students().filtered(lambda s: s.id == int(student_id))
        event = request.env['event.event'].sudo().browse(event_id)
        if students and event.exists():
            existing = request.env['event.registration'].sudo().search([
                ('event_id', '=', event.id), ('student_id', '=', students.id),
            ], limit=1)
            if not existing:
                request.env['event.registration'].sudo().create({
                    'event_id': event.id,
                    'student_id': students.id,
                    'partner_id': students.partner_id.id,
                })
        return request.redirect('/my/events')
