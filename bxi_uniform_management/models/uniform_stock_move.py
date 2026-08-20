from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class UniformStockMove(models.Model):
    _name = 'bxi.uniform.stock.move'
    _description = 'Uniform Stock Move'
    _order = 'date desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default=lambda self: _('New'))
    stock_id = fields.Many2one('bxi.uniform.stock', required=True, ondelete='cascade')
    product_id = fields.Many2one(related='stock_id.product_id', store=True)
    move_type = fields.Selection([
        ('receipt', 'Stock Receipt'),
        ('issue', 'Issued to Patron'),
        ('return', 'Returned to Stock'),
        ('adjustment', 'Adjustment'),
    ], required=True, default='receipt')
    quantity = fields.Float(required=True, help='Signed: positive increases stock, negative decreases.')
    date = fields.Datetime(default=fields.Datetime.now, required=True)
    order_id = fields.Many2one('bxi.uniform.order', ondelete='set null')
    processed_by = fields.Many2one('res.users', default=lambda self: self.env.user)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ], default='posted', required=True)
    note = fields.Char()
    company_id = fields.Many2one('res.company', related='stock_id.company_id', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.uniform.stock.move') or _('New')
        return super().create(vals_list)

    @api.constrains('quantity', 'move_type')
    def _check_quantity_sign(self):
        for record in self:
            if record.move_type in ('receipt', 'return') and record.quantity <= 0:
                raise ValidationError(_('%s quantity must be positive.') % dict(self._fields['move_type'].selection).get(record.move_type))
            if record.move_type == 'issue' and record.quantity >= 0:
                raise ValidationError(_('Issue quantity must be negative.'))
            if record.move_type == 'adjustment' and record.quantity == 0:
                raise ValidationError(_('Adjustment quantity cannot be zero.'))
