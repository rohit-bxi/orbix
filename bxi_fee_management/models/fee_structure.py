from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .fee_category import FEE_FREQUENCIES

LATE_FEE_TYPES = [
    ('fixed', 'Fixed Amount'),
    ('percentage', 'Percentage'),
    ('per_day', 'Per Day'),
]

DISCOUNT_TYPES = [
    ('percentage', 'Percentage'),
    ('fixed', 'Fixed Amount'),
]

INSTALLMENT_TYPES = [
    ('one_time', 'One Time'),
    ('n_installments', 'Multiple Installments'),
    ('custom', 'Custom'),
]


class FeeStructureCategoryLine(models.Model):
    _name = 'bxi.fee.structure.category.line'
    _description = 'Fee Structure Category Line'
    _order = 'sequence, id'

    structure_id = fields.Many2one('op.fees.terms', string='Fee Structure', required=True, ondelete='cascade')
    category_id = fields.Many2one('bxi.fee.category', string='Fee Category', required=True)
    amount = fields.Monetary(required=True)
    frequency = fields.Selection(FEE_FREQUENCIES, required=True, default='annual')
    sequence = fields.Integer(default=10)
    currency_id = fields.Many2one(related='structure_id.currency_id')
    structure_state = fields.Selection(related='structure_id.state', string='Status', store=True)
    structure_course_ids = fields.Many2many(related='structure_id.course_ids', string='Applicable Classes')

    @api.onchange('category_id')
    def _onchange_category_id(self):
        if self.category_id:
            self.frequency = self.category_id.default_frequency

    @api.constrains('amount')
    def _check_amount(self):
        for line in self:
            if line.amount <= 0:
                raise UserError(_('Fee category amount must be greater than zero.'))


class FeeStructure(models.Model):
    """Extends OpenEduCat's op.fees.terms with the fields the Fee Structure
    Setup screens need (academic year/class/section scope, a flat fee
    category breakdown, a payment-schedule generator, late fee and discount
    rules, and an activate/deactivate lifecycle), while leaving the existing
    line_ids/fees_element_line engine that drives get_invoice() untouched
    underneath.
    """
    _inherit = 'op.fees.terms'

    academic_year_id = fields.Many2one('op.academic.year', string='Academic Year')
    course_ids = fields.Many2many('op.course', string='Applicable Classes',
                                   help='Leave empty to apply this structure to all classes.')
    batch_ids = fields.Many2many('op.batch', string='Applicable Sections',
                                  help='Leave empty to apply this structure to all sections.')
    currency_id = fields.Many2one('res.currency', string='Currency', default=lambda self: self.env.company.currency_id)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ], default='draft', required=True, tracking=True)

    category_line_ids = fields.One2many('bxi.fee.structure.category.line', 'structure_id', string='Fee Categories')
    total_amount = fields.Monetary(compute='_compute_total_amount', store=True)

    installment_type = fields.Selection(INSTALLMENT_TYPES, default='one_time', required=True)
    installment_count = fields.Integer(string='Number of Installments', default=2)
    first_due_date = fields.Date(string='First Due Date')
    payment_mode_note = fields.Char(
        string='Payment Mode',
        help='Free-text note on accepted payment modes for this structure (Cash, Cheque, Bank Transfer, Online, ...).')
    grace_period_days = fields.Integer(string='Grace Period (days)', default=0)

    late_fee_enabled = fields.Boolean(string='Enable Late Fee')
    late_fee_type = fields.Selection(LATE_FEE_TYPES, default='fixed')
    late_fee_amount = fields.Float(string='Late Fee Amount')
    late_fee_max_cap = fields.Monetary(string='Maximum Late Fee Cap')
    late_fee_apply_after_days = fields.Integer(string='Apply After (days)', default=0)

    discount_enabled = fields.Boolean(string='Enable Early Payment Discount')
    discount_type = fields.Selection(DISCOUNT_TYPES, default='percentage')
    discount_amount = fields.Float(string='Discount Amount')
    discount_valid_until = fields.Date(string='Valid Until')
    allow_sibling_discount = fields.Boolean(string='Allow Sibling Discount')

    auto_reminder = fields.Boolean(string='Send automatic payment reminders')
    auto_receipt = fields.Boolean(string='Auto-generate receipts on payment')
    allow_partial_payment = fields.Boolean(string='Allow partial payments', default=True)
    notify_admin_on_payment = fields.Boolean(string='Notify admin on payment')

    internal_notes = fields.Text(string='Internal Notes')
    parent_instructions = fields.Text(string='Payment Instructions for Parents')

    assigned_student_count = fields.Integer(compute='_compute_assignment_stats')
    active_payment_count = fields.Integer(compute='_compute_assignment_stats')
    pending_payment_count = fields.Integer(compute='_compute_assignment_stats')

    @api.depends('category_line_ids.amount')
    def _compute_total_amount(self):
        for structure in self:
            structure.total_amount = sum(structure.category_line_ids.mapped('amount'))

    def _compute_assignment_stats(self):
        details_model = self.env['op.student.fees.details']
        for structure in self:
            details = details_model.search([('fees_line_id.fees_id', '=', structure.id)])
            structure.assigned_student_count = len(details.student_id)
            structure.active_payment_count = len(
                details.filtered(lambda d: d.collection_status in ('paid', 'partially_paid')))
            structure.pending_payment_count = len(
                details.filtered(lambda d: d.collection_status in ('pending', 'overdue')))

    def action_generate_installments(self):
        for structure in self:
            if not structure.first_due_date:
                raise UserError(_('Set a First Due Date before generating the payment schedule.'))
            if structure.installment_type == 'custom':
                continue
            count = 1 if structure.installment_type == 'one_time' else max(structure.installment_count, 1)
            remaining = 100.0
            line_vals = []
            for i in range(count):
                pct = round(100.0 / count, 2) if i < count - 1 else round(remaining, 2)
                remaining -= pct
                line_vals.append((0, 0, {
                    'due_date': structure.first_due_date + relativedelta(months=i),
                    'value': pct,
                }))
            structure.write({
                'fees_terms': 'fixed_date',
                'line_ids': [(5, 0, 0)] + line_vals,
            })
            structure._sync_category_lines_to_elements()

    def action_recalculate_categories(self):
        for structure in self:
            if not structure.line_ids:
                raise UserError(_('Generate the payment schedule first.'))
            structure._sync_category_lines_to_elements()

    def _sync_category_lines_to_elements(self):
        for structure in self:
            total = sum(structure.category_line_ids.mapped('amount'))
            for line in structure.line_ids:
                line.fees_element_line.unlink()
                if not total:
                    continue
                element_vals = [(0, 0, {
                    'product_id': cat.category_id.product_id.id,
                    'value': cat.amount / total * 100.0,
                }) for cat in structure.category_line_ids]
                line.write({'fees_element_line': element_vals})

    def action_activate(self):
        for structure in self:
            if not structure.category_line_ids:
                raise UserError(_('Add at least one fee category before activating this structure.'))
            if not structure.line_ids:
                raise UserError(_('Generate the payment schedule before activating this structure.'))
        self.write({'state': 'active'})

    def action_set_draft(self):
        self.write({'state': 'draft'})

    def action_set_inactive(self):
        self.write({'state': 'inactive'})

    def action_deactivate(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Deactivate Fee Structure'),
            'res_model': 'bxi.fee.structure.deactivate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_structure_id': self.id},
        }

    def action_view_assigned_students(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Fee Collection'),
            'res_model': 'op.student.fees.details',
            'view_mode': 'list,form',
            'domain': [('structure_id', '=', self.id)],
        }

    def action_duplicate(self):
        self.ensure_one()
        copy = self.copy({'name': _('%s (Copy)') % self.name, 'state': 'draft'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'op.fees.terms',
            'view_mode': 'form',
            'res_id': copy.id,
        }
