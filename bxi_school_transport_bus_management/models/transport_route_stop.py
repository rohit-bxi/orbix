from odoo import api, fields, models


class TransportRouteStop(models.Model):
    _name = 'bxi.transport.route.stop'
    _description = 'Bus Route Stop'
    _order = 'route_id, sequence, id'

    route_id = fields.Many2one('bxi.transport.route', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    pickup_time = fields.Float(string='Pickup Time')
    drop_time = fields.Float(string='Drop Time')
    fee_amount = fields.Monetary(string='Stop Fee')
    currency_id = fields.Many2one(related='route_id.currency_id', readonly=True)
    registration_ids = fields.One2many('bxi.transport.registration', 'stop_id', string='Registrations')
    registration_count = fields.Integer(compute='_compute_registration_count')

    @api.depends('registration_ids.state')
    def _compute_registration_count(self):
        for stop in self:
            stop.registration_count = len(stop.registration_ids.filtered(lambda r: r.state != 'cancelled'))

    @api.onchange('route_id')
    def _onchange_route_id(self):
        if self.route_id and not self.fee_amount:
            self.fee_amount = self.route_id.fee_amount
