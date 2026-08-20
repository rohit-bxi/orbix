from odoo import fields, models, api


class OpStudent(models.Model):
    _name = 'op.student'
    _inherit = ['op.student']

    uniform_order_ids = fields.One2many('bxi.uniform.order', 'student_id', string='Uniform Orders')
    uniform_order_count = fields.Integer(compute='_compute_uniform_order_count')

    @api.depends('uniform_order_ids')
    def _compute_uniform_order_count(self):
        for record in self:
            record.uniform_order_count = len(record.uniform_order_ids)

    def action_view_uniform_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Uniform Orders',
            'res_model': 'bxi.uniform.order',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }
