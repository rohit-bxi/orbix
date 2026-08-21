from odoo import api, fields, models


class OpStudent(models.Model):
    _name = 'op.student'
    _inherit = 'op.student'

    event_registration_ids = fields.One2many('event.registration', 'student_id', string='Event Registrations')
    event_registration_count = fields.Integer(compute='_compute_event_registration_count')

    @api.depends('event_registration_ids')
    def _compute_event_registration_count(self):
        for rec in self:
            rec.event_registration_count = len(rec.event_registration_ids)

    def action_view_event_registrations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Events',
            'res_model': 'event.registration',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }
