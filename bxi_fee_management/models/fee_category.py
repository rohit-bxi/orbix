from odoo import fields, models

FEE_FREQUENCIES = [
    ('one_time', 'One Time'),
    ('monthly', 'Monthly'),
    ('quarterly', 'Quarterly'),
    ('half_yearly', 'Half-Yearly'),
    ('annual', 'Annual'),
    ('per_semester', 'Per Semester'),
]


class FeeCategory(models.Model):
    _name = 'bxi.fee.category'
    _description = 'Fee Category'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char()
    product_id = fields.Many2one(
        'product.product', string='Linked Product', required=True,
        help='Drives the accounting/GL mapping for this fee category, the same product used by '
             "OpenEduCat's fee element/invoicing engine.")
    default_frequency = fields.Selection(FEE_FREQUENCIES, string='Default Frequency', default='annual', required=True)
    is_refundable = fields.Boolean(default=True, help='Whether this fee head can be refunded, read by the refund module.')
    sequence = fields.Integer(default=10)
    color = fields.Integer()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
