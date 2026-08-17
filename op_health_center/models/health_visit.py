from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class HealthVisit(models.Model):
    _name = 'op.health.visit'
    _description = 'Health Visit'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'op.health.patient.mixin']
    _order = 'visit_datetime desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default=lambda self: _('New'))
    visit_datetime = fields.Datetime(string='Visit Date', required=True, default=fields.Datetime.now, tracking=True)
    visit_type = fields.Selection([
        ('illness', 'Illness'),
        ('injury', 'Injury'),
        ('routine', 'Routine'),
        ('other', 'Other'),
    ], default='illness', tracking=True)
    reported_by = fields.Many2one('res.users', string='Reported By', default=lambda self: self.env.user)
    symptoms = fields.Text()
    diagnosis = fields.Text()
    treatment_given = fields.Text()
    attended_by = fields.Many2one(
        'hr.employee', string='Attended By', domain=[('is_health_staff', '=', True)], tracking=True)
    referred_to_hospital = fields.Boolean(string='Referred to Hospital', tracking=True)
    hospital_name = fields.Char()
    follow_up_required = fields.Boolean()
    follow_up_date = fields.Date()
    parent_or_guardian_notified = fields.Boolean(string='Parent/Guardian Notified', tracking=True)
    notified_on = fields.Datetime()
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('under_treatment', 'Under Treatment'),
        ('resolved', 'Resolved'),
        ('referred', 'Referred'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('op.health.visit') or _('New')
        return super().create(vals_list)

    @api.constrains('follow_up_required', 'follow_up_date', 'visit_datetime')
    def _check_follow_up_date(self):
        for record in self:
            if record.follow_up_required:
                if not record.follow_up_date:
                    raise ValidationError(_('Follow-up Date is required when Follow-up Required is set.'))
                if record.visit_datetime and record.follow_up_date < record.visit_datetime.date():
                    raise ValidationError(_('Follow-up Date cannot be before the Visit Date.'))

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_start_treatment(self):
        self.write({'state': 'under_treatment'})

    def action_resolve(self):
        self.write({'state': 'resolved'})

    def action_refer(self):
        self.write({'state': 'referred'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})
