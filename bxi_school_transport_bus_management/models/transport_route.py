from odoo import api, fields, models


class TransportRoute(models.Model):
    _name = 'bxi.transport.route'
    _description = 'Bus Route'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char()
    academic_year_id = fields.Many2one('op.academic.year', string='Academic Year', tracking=True)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Bus', required=True, tracking=True,
        domain=[('is_school_bus', '=', True)])
    driver_id = fields.Many2one(related='vehicle_id.driver_id', string='Driver', store=True, readonly=True)
    attendant_id = fields.Many2one(
        related='vehicle_id.bus_attendant_id', string='Attendant', store=True, readonly=True)
    capacity = fields.Integer(related='vehicle_id.seats', string='Capacity', store=True, readonly=True)
    distance_km = fields.Float(string='Distance (km)')
    fee_product_id = fields.Many2one(
        'product.product', string='Fee Product', required=True,
        domain=[('type', '=', 'service')],
        default=lambda self: self.env.ref(
            'bxi_school_transport_bus_management.product_transport_fee', raise_if_not_found=False))
    fee_amount = fields.Monetary(string='Default Monthly Fee')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    stop_ids = fields.One2many('bxi.transport.route.stop', 'route_id', string='Stops', copy=True)
    registration_ids = fields.One2many('bxi.transport.registration', 'route_id', string='Registrations')
    registration_count = fields.Integer(compute='_compute_registration_count')
    seats_available = fields.Integer(compute='_compute_seats_available', string='Seats Available')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('archived', 'Archived'),
    ], default='draft', required=True, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    _unique_code = models.Constraint('unique(code, company_id)', 'Route code must be unique.')

    @api.depends('registration_ids.state')
    def _compute_registration_count(self):
        for route in self:
            route.registration_count = len(route.registration_ids.filtered(lambda r: r.state != 'cancelled'))

    @api.depends('capacity', 'registration_ids.state')
    def _compute_seats_available(self):
        for route in self:
            active_regs = len(route.registration_ids.filtered(lambda r: r.state in ('confirmed', 'active')))
            route.seats_available = route.capacity - active_regs

    def action_activate(self):
        self.write({'state': 'active'})

    def action_archive_route(self):
        self.write({'state': 'archived', 'active': False})

    def action_set_draft(self):
        self.write({'state': 'draft', 'active': True})

    def action_view_registrations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Registrations',
            'res_model': 'bxi.transport.registration',
            'view_mode': 'list,form',
            'domain': [('route_id', '=', self.id)],
            'context': {'default_route_id': self.id},
        }
