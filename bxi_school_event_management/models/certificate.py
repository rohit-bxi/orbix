from odoo import fields, models


class OpCertificate(models.Model):
    _inherit = 'op.certificate'

    event_registration_id = fields.Many2one('event.registration', readonly=True, copy=False)
