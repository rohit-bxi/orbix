from odoo import api, fields, models


class OpParent(models.Model):
    _inherit = 'op.parent'

    child_event_registration_count = fields.Integer(compute='_compute_child_event_registration_count')

    @api.depends('student_ids')
    def _compute_child_event_registration_count(self):
        for rec in self:
            rec.child_event_registration_count = self.env['event.registration'].search_count(
                [('student_id', 'in', rec.student_ids.ids)]) if rec.student_ids else 0

    def action_view_child_event_registrations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': "Children's Events",
            'res_model': 'event.registration',
            'view_mode': 'list,form',
            'domain': [('student_id', 'in', self.student_ids.ids)],
        }
