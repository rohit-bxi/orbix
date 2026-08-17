from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class TransportRegistration(models.Model):
    _name = 'bxi.transport.registration'
    _description = 'Student Transport Registration'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default=lambda self: _('New'))
    student_id = fields.Many2one('op.student', required=True, tracking=True)
    academic_year_id = fields.Many2one(related='route_id.academic_year_id', store=True, readonly=True)
    route_id = fields.Many2one(
        'bxi.transport.route', required=True, tracking=True, domain=[('state', '=', 'active')])
    stop_id = fields.Many2one(
        'bxi.transport.route.stop', required=True, tracking=True,
        domain="[('route_id', '=', route_id)]")
    pickup_time = fields.Float(related='stop_id.pickup_time', readonly=True)
    drop_time = fields.Float(related='stop_id.drop_time', readonly=True)
    date_start = fields.Date(required=True, default=fields.Date.today, tracking=True)
    date_end = fields.Date(tracking=True)
    fee_amount = fields.Monetary(compute='_compute_fee_amount', store=True, readonly=False)
    currency_id = fields.Many2one(related='route_id.currency_id', readonly=True)
    invoice_id = fields.Many2one('account.move', readonly=True, copy=False)
    invoice_payment_state = fields.Selection(related='invoice_id.payment_state', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('stop_id', 'route_id')
    def _compute_fee_amount(self):
        for reg in self:
            reg.fee_amount = reg.stop_id.fee_amount or reg.route_id.fee_amount

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.transport.registration') or _('New')
        return super().create(vals_list)

    @api.constrains('route_id', 'stop_id')
    def _check_stop_on_route(self):
        for reg in self:
            if reg.stop_id and reg.stop_id.route_id != reg.route_id:
                raise ValidationError(_('The selected stop does not belong to the selected route.'))

    @api.constrains('student_id', 'state')
    def _check_single_active_registration(self):
        for reg in self:
            if reg.state == 'cancelled':
                continue
            domain = [
                ('student_id', '=', reg.student_id.id),
                ('state', '!=', 'cancelled'),
                ('id', '!=', reg.id),
            ]
            if self.search_count(domain):
                raise ValidationError(
                    _('%s already has an active transport registration. Cancel it first.') % reg.student_id.name)

    def action_confirm(self):
        for reg in self:
            if reg.route_id.seats_available <= 0:
                raise ValidationError(_('No seats available on route %s.') % reg.route_id.name)
            reg._create_invoice()
            reg.state = 'confirmed'

    def _create_invoice(self):
        self.ensure_one()
        if self.invoice_id:
            return self.invoice_id
        product = self.route_id.fee_product_id
        if not product:
            raise UserError(_('Please configure a fee product on route %s.') % self.route_id.name)
        account_id = product.property_account_income_id.id \
            or product.categ_id.property_account_income_categ_id.id
        if not account_id:
            raise UserError(_('There is no income account defined for product "%s".') % product.name)
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.student_id.partner_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': _('Transport Fee - %(route)s (%(stop)s)') % {
                    'route': self.route_id.name, 'stop': self.stop_id.name},
                'account_id': account_id,
                'product_id': product.id,
                'quantity': 1.0,
                'price_unit': self.fee_amount,
            })],
        })
        invoice._compute_tax_totals()
        self.invoice_id = invoice.id
        return invoice

    def action_view_invoice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.invoice_id.id,
        }

    def action_activate(self):
        for reg in self:
            if reg.invoice_id and reg.invoice_id.payment_state not in ('paid', 'in_payment'):
                raise ValidationError(
                    _('The transport fee invoice must be paid before activating this registration.'))
            reg.state = 'active'

    def action_cancel(self):
        for reg in self:
            if reg.invoice_id and reg.invoice_id.state == 'draft':
                reg.invoice_id.button_cancel()
            reg.state = 'cancelled'

    def action_set_draft(self):
        self.write({'state': 'draft'})
