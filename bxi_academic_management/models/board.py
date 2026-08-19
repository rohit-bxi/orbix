from odoo import fields, models


class BxiBoard(models.Model):
    _name = 'bxi.board'
    _description = 'Education Board'
    _order = 'name'

    name = fields.Char('Name', required=True)
    active = fields.Boolean(default=True)

    _unique_name = models.Constraint(
        'unique(name)',
        'A board with this name already exists.',
    )
