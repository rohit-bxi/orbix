from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    student_id = fields.Many2one(
        'op.student', string='Student', ondelete='cascade', index=True,
        help='Set only on the lightweight shadow employee record created '
             'for a student so the standard check-in/out flow (kiosk, '
             'systray, badge/PIN) can be used for student attendance.')
