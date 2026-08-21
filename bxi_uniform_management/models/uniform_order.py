from odoo import fields, models, api, _
from odoo.exceptions import ValidationError, AccessError, UserError

GENDER_MAP = {'m': 'boy', 'f': 'girl', 'o': 'unisex'}


class UniformOrder(models.Model):
    _name = 'bxi.uniform.order'
    _description = 'Uniform Order'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'bxi.uniform.patron.mixin']
    _order = 'order_date desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default=lambda self: _('New'))
    order_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    order_line_ids = fields.One2many('bxi.uniform.order.line', 'order_id', string='Order Lines')
    total_amount = fields.Monetary(compute='_compute_total_amount', store=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('issued', 'Issued'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True)
    invoice_id = fields.Many2one('account.move', readonly=True, copy=False)
    invoice_payment_state = fields.Selection(related='invoice_id.payment_state', readonly=True)
    issued_by = fields.Many2one('res.users', readonly=True, copy=False)
    cancel_reason = fields.Char()
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('order_line_ids.price_subtotal')
    def _compute_total_amount(self):
        for order in self:
            order.total_amount = sum(order.order_line_ids.mapped('price_subtotal'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.uniform.order') or _('New')
        return super().create(vals_list)

    def action_load_from_policy(self):
        self.ensure_one()
        if not self.student_id:
            raise UserError(_('Load from Policy is only available for student orders.'))
        if self.order_line_ids:
            raise UserError(_('Clear the existing order lines before loading a policy.'))
        course_detail = self.student_id.course_detail_ids.filtered(lambda c: c.state == 'running')[:1] \
            or self.student_id.course_detail_ids[:1]
        if not course_detail:
            raise UserError(_('%s has no course assigned.') % self.student_id.name)
        gender = GENDER_MAP.get(self.student_id.gender, 'unisex')
        # 'gender' orders before 'unisex' alphabetically, so an exact-gender
        # policy is picked over a unisex fallback when both exist.
        policy = self.env['bxi.uniform.policy'].search([
            ('course_id', '=', course_detail.course_id.id),
            ('gender', 'in', (gender, 'unisex')),
        ], limit=1, order='gender')
        if not policy:
            raise UserError(_('No uniform policy found for %s.') % course_detail.course_id.name)
        lines = [(0, 0, {
            'product_id': line.product_tmpl_id.product_variant_id.id,
            'quantity': line.quantity,
            'price_unit': line.product_tmpl_id.list_price,
        }) for line in policy.line_ids if line.product_tmpl_id.product_variant_id]
        self.order_line_ids = lines

    def action_confirm(self):
        for order in self:
            if order.state != 'draft':
                raise ValidationError(_('Only a draft order can be confirmed.'))
            if not order.order_line_ids:
                raise ValidationError(_('Add at least one order line before confirming.'))
            order._create_invoice()
            order.state = 'confirmed'

    def _create_invoice(self):
        self.ensure_one()
        if self.invoice_id:
            return self.invoice_id
        partner = self.student_id.partner_id or self.faculty_id.partner_id
        invoice_lines = []
        for line in self.order_line_ids:
            product = line.product_id
            account_id = product.property_account_income_id.id \
                or product.categ_id.property_account_income_categ_id.id
            if not account_id:
                raise UserError(_('There is no income account defined for product "%s".') % product.name)
            invoice_lines.append((0, 0, {
                'name': product.display_name,
                'account_id': account_id,
                'product_id': product.id,
                'quantity': line.quantity,
                'price_unit': line.price_unit,
            }))
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_origin': self.name,
            'invoice_line_ids': invoice_lines,
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

    def _check_stock_availability(self):
        self.ensure_one()
        shortages = []
        for line in self.order_line_ids:
            stock = self.env['bxi.uniform.stock']._get_or_create(line.product_id.id)
            if stock.quantity_on_hand < line.quantity:
                shortages.append(_('%(product)s: available %(available)s, requested %(requested)s') % {
                    'product': line.product_id.display_name,
                    'available': stock.quantity_on_hand,
                    'requested': line.quantity,
                })
        return shortages

    def _issue_stock(self):
        self.ensure_one()
        for line in self.order_line_ids:
            stock = self.env['bxi.uniform.stock']._get_or_create(line.product_id.id)
            self.env['bxi.uniform.stock.move'].create({
                'stock_id': stock.id,
                'move_type': 'issue',
                'quantity': -line.quantity,
                'order_id': self.id,
            })

    def action_mark_issued(self):
        for order in self:
            if order.state != 'confirmed':
                raise ValidationError(_('Only a confirmed order can be issued.'))
            shortages = order._check_stock_availability()
            if shortages:
                raise ValidationError(_('Insufficient stock:\n%s') % '\n'.join(shortages))
            order._issue_stock()
            order.write({'state': 'issued', 'issued_by': self.env.user.id})

    def action_force_issue(self):
        if not self.env.user.has_group('bxi_uniform_management.group_uniform_manager'):
            raise AccessError(_('Only a Uniform Manager can force-issue an order over available stock.'))
        for order in self:
            if order.state != 'confirmed':
                raise ValidationError(_('Only a confirmed order can be issued.'))
            order._issue_stock()
            order.write({'state': 'issued', 'issued_by': self.env.user.id})

    def action_cancel(self):
        for order in self:
            if order.invoice_id and order.invoice_id.state == 'draft':
                order.invoice_id.button_cancel()
            if order.state == 'issued':
                for line in order.order_line_ids:
                    stock = self.env['bxi.uniform.stock']._get_or_create(line.product_id.id)
                    self.env['bxi.uniform.stock.move'].create({
                        'stock_id': stock.id,
                        'move_type': 'return',
                        'quantity': line.quantity,
                        'order_id': order.id,
                        'note': order.cancel_reason,
                    })
            order.write({'state': 'cancelled'})

    def action_set_draft(self):
        self.write({'state': 'draft'})
