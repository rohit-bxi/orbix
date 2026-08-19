from odoo import _, fields, models


class BxiCurriculum(models.Model):
    _name = 'bxi.curriculum'
    _description = 'Academic Curriculum'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char('Curriculum Name', required=True, tracking=True)
    board_id = fields.Many2one('bxi.board', string='Board', required=True, tracking=True)
    description = fields.Text('Description', required=True)
    class_ids = fields.Many2many('op.course', string='Assigned Classes', tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    _unique_name_board = models.Constraint(
        'unique(name, board_id)',
        'A curriculum with this Name and Board already exists.',
    )

    def action_open_assign_classes(self):
        self.ensure_one()
        view = self.env.ref('bxi_academic_management.view_curriculum_form_assign_classes')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Assign Classes'),
            'res_model': 'bxi.curriculum',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(view.id, 'form')],
            'target': 'current',
        }
