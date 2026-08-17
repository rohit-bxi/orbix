from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class TransportDriver(models.Model):
    _name = 'bxi.transport.driver'
    _description = 'Transport Driver'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'

    partner_id = fields.Many2one('res.partner', string='Driver', required=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee')
    name = fields.Char(related='partner_id.name', store=True, readonly=True)
    phone = fields.Char(related='partner_id.phone', readonly=True)
    license_number = fields.Char(required=True, tracking=True)
    license_type = fields.Selection([
        ('lmv', 'Light Motor Vehicle'),
        ('hmv', 'Heavy Motor Vehicle'),
        ('psv', 'Public Service Vehicle Badge'),
    ], required=True, tracking=True)
    license_expiry = fields.Date(required=True, tracking=True)
    license_expiring_soon = fields.Boolean(compute='_compute_license_expiring_soon', store=True)
    badge_verified = fields.Boolean(string='Police Verification Done')
    status = fields.Selection([
        ('active', 'Active'),
        ('on_leave', 'On Leave'),
        ('suspended', 'Suspended'),
    ], default='active', required=True, tracking=True)
    vehicle_id = fields.Many2one('fleet.vehicle', compute='_compute_vehicle_id', string='Current Vehicle')
    route_ids = fields.One2many('bxi.transport.route', compute='_compute_route_ids', string='Routes')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    _unique_partner = models.Constraint('unique(partner_id)', 'This person already has a driver profile.')

    @api.depends('license_expiry')
    def _compute_license_expiring_soon(self):
        today = fields.Date.today()
        for driver in self:
            driver.license_expiring_soon = bool(
                driver.license_expiry and 0 <= (driver.license_expiry - today).days <= 30)

    def _compute_vehicle_id(self):
        for driver in self:
            driver.vehicle_id = self.env['fleet.vehicle'].search(
                [('driver_id', '=', driver.partner_id.id), ('is_school_bus', '=', True)], limit=1)

    def _compute_route_ids(self):
        for driver in self:
            driver.route_ids = self.env['bxi.transport.route'].search(
                [('vehicle_id.driver_id', '=', driver.partner_id.id)])

    def action_view_vehicle(self):
        self.ensure_one()
        if not self.vehicle_id:
            raise ValidationError(_('This driver is not currently assigned to any bus.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.vehicle',
            'view_mode': 'form',
            'res_id': self.vehicle_id.id,
        }

    def _cron_check_license_expiry(self):
        drivers = self.search([('license_expiring_soon', '=', True), ('active', '=', True)])
        manager_group = self.env.ref(
            'bxi_school_transport_bus_management.group_transport_manager', raise_if_not_found=False)
        activity_type = self.env.ref('mail.mail_activity_data_todo')
        recipient = manager_group.user_ids[:1] if manager_group and manager_group.user_ids else self.env.user
        for driver in drivers:
            has_open_activity = driver.activity_ids.filtered(lambda a: a.activity_type_id == activity_type)
            if has_open_activity:
                continue
            driver.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('Driving license expiring soon'),
                note=_('License %(number)s expires on %(date)s. Please renew.') % {
                    'number': driver.license_number, 'date': driver.license_expiry},
                user_id=recipient.id,
            )
