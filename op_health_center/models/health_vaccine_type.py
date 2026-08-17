from odoo import fields, models


class HealthVaccineType(models.Model):
    _name = 'op.health.vaccine.type'
    _description = 'Vaccine Type'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char()
    doses_required = fields.Integer(string='Doses Required', default=1)
    description = fields.Text()
    active = fields.Boolean(default=True)
