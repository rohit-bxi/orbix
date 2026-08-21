from odoo import _, fields, models
from odoo.exceptions import UserError


class EventRegistration(models.Model):
    _inherit = 'event.registration'

    student_id = fields.Many2one('op.student', string='Student')
    parent_id = fields.Many2one('op.parent', string='Booked By (Parent)')

    permission_slip_signed = fields.Boolean()
    signed_by = fields.Char()
    signed_date = fields.Date()

    transport_registration_id = fields.Many2one('bxi.transport.registration', readonly=True, copy=False)
    invoice_id = fields.Many2one('account.move', readonly=True, copy=False)
    invoice_payment_state = fields.Selection(related='invoice_id.payment_state', readonly=True)
    certificate_id = fields.Many2one('op.certificate', readonly=True, copy=False)

    def action_confirm(self):
        for reg in self:
            if reg.event_id.is_paid_event:
                if not reg.invoice_id:
                    reg.invoice_id = reg._create_registration_invoice()
                if reg.invoice_id.payment_state not in ('paid', 'in_payment'):
                    raise UserError(_('Payment is required before this registration can be confirmed.'))
            if reg.event_id.requires_permission_slip and not reg.permission_slip_signed:
                raise UserError(_('A signed permission slip is required before this registration can be confirmed.'))
        return super().action_confirm()

    def _create_registration_invoice(self):
        self.ensure_one()
        if self.invoice_id:
            return self.invoice_id
        if not self.student_id:
            raise UserError(_('A student must be set on this registration before it can be invoiced.'))
        product = self.event_id.fee_product_id
        if not product:
            raise UserError(_('Please configure a fee product on event "%s".') % self.event_id.name)
        account_id = product.property_account_income_id.id \
            or product.categ_id.property_account_income_categ_id.id
        if not account_id:
            raise UserError(_('There is no income account defined for product "%s".') % product.name)
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.student_id.partner_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': _('Event Fee - %s') % self.event_id.name,
                'account_id': account_id,
                'product_id': product.id,
                'quantity': 1.0,
                'price_unit': product.lst_price,
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

    def action_sign_permission_slip(self, signed_by):
        self.ensure_one()
        self.write({
            'permission_slip_signed': True,
            'signed_by': signed_by,
            'signed_date': fields.Date.context_today(self),
        })

    def action_add_transport(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Book Transport'),
            'res_model': 'bxi.transport.registration',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_student_id': self.student_id.id,
                'default_event_registration_id': self.id,
            },
        }
