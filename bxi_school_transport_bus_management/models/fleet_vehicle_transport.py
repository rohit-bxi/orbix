from odoo import api, fields, models


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    is_school_bus = fields.Boolean(string='School Bus', tracking=True)
    academic_year_id = fields.Many2one('op.academic.year', string='Academic Year')
    bus_attendant_id = fields.Many2one('res.partner', string='Bus Attendant/Conductor')
    route_ids = fields.One2many('bxi.transport.route', 'vehicle_id', string='Routes')
    route_count = fields.Integer(compute='_compute_route_count')
    transport_driver_id = fields.Many2one(
        'bxi.transport.driver', string='Driver Profile',
        compute='_compute_transport_driver_id')

    @api.depends('route_ids')
    def _compute_route_count(self):
        for vehicle in self:
            vehicle.route_count = len(vehicle.route_ids)

    @api.depends('driver_id')
    def _compute_transport_driver_id(self):
        for vehicle in self:
            vehicle.transport_driver_id = self.env['bxi.transport.driver'].search(
                [('partner_id', '=', vehicle.driver_id.id)], limit=1) if vehicle.driver_id else False

    def action_view_routes(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Routes',
            'res_model': 'bxi.transport.route',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }
