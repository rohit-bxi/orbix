from odoo import fields, models


class ResourceCalendarLeaves(models.Model):
    _inherit = ['resource.calendar.leaves', 'mail.thread']
    _name = 'resource.calendar.leaves'

    name = fields.Char(required=True)
    description = fields.Text('Description', tracking=True)
