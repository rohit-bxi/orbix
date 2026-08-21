from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EventBulkRegistrationWizard(models.TransientModel):
    _name = 'event.bulk.registration.wizard'
    _description = 'Bulk Register Students for an Event'

    event_id = fields.Many2one('event.event', required=True)
    course_id = fields.Many2one('op.course', string='Class')
    batch_id = fields.Many2one('op.batch', string='Section')
    student_ids = fields.Many2many('op.student', string='Students')

    @api.onchange('event_id')
    def _onchange_event_id(self):
        if self.event_id:
            self.course_id = self.event_id.course_ids[:1]
            self.batch_id = self.event_id.batch_ids[:1]

    @api.onchange('course_id', 'batch_id')
    def _onchange_course_batch(self):
        if not self.course_id and not self.batch_id:
            self.student_ids = False
            return
        domain = [('state', '=', 'running')]
        if self.batch_id:
            domain.append(('batch_id', '=', self.batch_id.id))
        elif self.course_id:
            domain.append(('course_id', '=', self.course_id.id))
        course_details = self.env['op.student.course'].search(domain)
        self.student_ids = course_details.mapped('student_id')

    def action_create_registrations(self):
        self.ensure_one()
        if not self.student_ids:
            raise UserError(_('Select at least one student.'))
        existing = self.env['event.registration'].search([
            ('event_id', '=', self.event_id.id),
            ('student_id', 'in', self.student_ids.ids),
        ]).mapped('student_id')
        registrations = self.env['event.registration']
        for student in self.student_ids - existing:
            registrations |= self.env['event.registration'].create({
                'event_id': self.event_id.id,
                'student_id': student.id,
                'partner_id': student.partner_id.id,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Registrations',
            'res_model': 'event.registration',
            'view_mode': 'list,form',
            'domain': [('event_id', '=', self.event_id.id)],
        }
