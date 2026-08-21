from odoo import api, fields, models


class OpStudent(models.Model):
    _name = 'op.student'
    _inherit = 'op.student'

    certificate_ids = fields.One2many('op.certificate', 'student_id', string='Certificates')
    certificate_count = fields.Integer(compute='_compute_certificate_count')

    @api.depends('certificate_ids')
    def _compute_certificate_count(self):
        for rec in self:
            rec.certificate_count = len(rec.certificate_ids)

    def action_view_certificates(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Certificates',
            'res_model': 'op.certificate',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }
