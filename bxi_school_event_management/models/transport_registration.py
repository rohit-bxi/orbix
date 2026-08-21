from odoo import api, fields, models


class BxiTransportRegistration(models.Model):
    _inherit = 'bxi.transport.registration'

    event_registration_id = fields.Many2one('event.registration', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.event_registration_id:
                record.event_registration_id.transport_registration_id = record.id
        return records
