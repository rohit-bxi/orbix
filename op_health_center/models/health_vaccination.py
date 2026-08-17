from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class HealthVaccination(models.Model):
    _name = 'op.health.vaccination'
    _description = 'Health Vaccination'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'op.health.patient.mixin']
    _order = 'scheduled_date desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default=lambda self: _('New'))
    vaccine_id = fields.Many2one('op.health.vaccine.type', string='Vaccine', required=True, tracking=True)
    dose_number = fields.Integer(string='Dose Number', default=1)
    scheduled_date = fields.Date()
    date_administered = fields.Date(tracking=True)
    administered_by = fields.Many2one(
        'hr.employee', string='Administered By', domain=[('is_health_staff', '=', True)])
    next_due_date = fields.Date(tracking=True)
    batch_no = fields.Char(string='Batch No.')
    certificate_ids = fields.Many2many('ir.attachment', string='Certificates')
    state = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('missed', 'Missed'),
        ('cancelled', 'Cancelled'),
    ], default='scheduled', tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('op.health.vaccination') or _('New')
        return super().create(vals_list)

    @api.constrains('state', 'date_administered')
    def _check_date_administered(self):
        for record in self:
            if record.state == 'completed' and not record.date_administered:
                raise ValidationError(_('Date Administered is required to complete a vaccination record.'))

    def action_complete(self):
        for record in self:
            record.write({
                'state': 'completed',
                'date_administered': record.date_administered or fields.Date.context_today(record),
            })

    def action_miss(self):
        self.write({'state': 'missed'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset(self):
        self.write({'state': 'scheduled'})

    @api.model
    def _cron_flag_overdue_vaccinations(self):
        today = fields.Date.context_today(self)
        overdue = self.search([('state', '=', 'scheduled'), ('next_due_date', '<', today)])
        overdue.write({'state': 'missed'})
