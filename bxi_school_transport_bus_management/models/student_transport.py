from odoo import api, fields, models


class OpStudent(models.Model):
    _name = 'op.student'
    _inherit = ['op.student']

    transport_registration_ids = fields.One2many(
        'bxi.transport.registration', 'student_id', string='Transport Registrations')
    current_transport_registration_id = fields.Many2one(
        'bxi.transport.registration', compute='_compute_current_transport_registration', store=True)
    transport_route_id = fields.Many2one(
        related='current_transport_registration_id.route_id', string='Bus Route')
    transport_stop_id = fields.Many2one(
        related='current_transport_registration_id.stop_id', string='Bus Stop')
    transport_count = fields.Integer(compute='_compute_transport_count')

    @api.depends('transport_registration_ids.state')
    def _compute_current_transport_registration(self):
        for student in self:
            student.current_transport_registration_id = student.transport_registration_ids.filtered(
                lambda r: r.state in ('confirmed', 'active'))[:1]

    @api.depends('transport_registration_ids')
    def _compute_transport_count(self):
        for student in self:
            student.transport_count = len(student.transport_registration_ids)

    def action_view_transport_registrations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Transport Registrations',
            'res_model': 'bxi.transport.registration',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }
