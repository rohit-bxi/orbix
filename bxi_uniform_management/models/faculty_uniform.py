from odoo import fields, models, api


class OpFaculty(models.Model):
    _name = 'op.faculty'
    _inherit = ['op.faculty']

    uniform_order_ids = fields.One2many('bxi.uniform.order', 'faculty_id', string='Uniform Orders')
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
            'domain': [('faculty_id', '=', self.id)],
            'context': {'default_faculty_id': self.id},
        }
