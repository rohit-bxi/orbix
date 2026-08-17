from odoo import fields, models, _
from odoo.exceptions import UserError


class TransportBulkRegistrationWizard(models.TransientModel):
    _name = 'bxi.transport.bulk.registration.wizard'
    _description = 'Bulk Register Students on a Bus Route'

    batch_id = fields.Many2one('op.batch', required=True)
    route_id = fields.Many2one('bxi.transport.route', required=True, domain=[('state', '=', 'active')])
    stop_id = fields.Many2one(
        'bxi.transport.route.stop', required=True, domain="[('route_id', '=', route_id)]")
    date_start = fields.Date(required=True, default=fields.Date.today)

    def action_register(self):
        self.ensure_one()
        student_courses = self.env['op.student.course'].search([('batch_id', '=', self.batch_id.id)])
        students = student_courses.mapped('student_id')
        if not students:
            raise UserError(_('No students found in the selected batch.'))
        already_registered = self.env['bxi.transport.registration'].search([
            ('student_id', 'in', students.ids),
            ('state', '!=', 'cancelled'),
        ]).mapped('student_id')
        to_register = students - already_registered
        if not to_register:
            raise UserError(_('All students in this batch already have an active transport registration.'))
        registration_model = self.env['bxi.transport.registration']
        for student in to_register:
            registration_model.create({
                'student_id': student.id,
                'route_id': self.route_id.id,
                'stop_id': self.stop_id.id,
                'date_start': self.date_start,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Transport Registrations',
            'res_model': 'bxi.transport.registration',
            'view_mode': 'list,form',
            'domain': [('student_id', 'in', to_register.ids)],
        }
