from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class HealthCheckup(models.Model):
    _name = 'op.health.checkup'
    _description = 'Health Checkup'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'op.health.patient.mixin']
    _order = 'checkup_date desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default=lambda self: _('New'))
    checkup_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    checkup_type = fields.Selection([
        ('annual', 'Annual'),
        ('sports', 'Sports'),
        ('pre_admission', 'Pre-Admission'),
        ('follow_up', 'Follow-up'),
        ('other', 'Other'),
    ], default='annual')
    height_cm = fields.Float(string='Height (cm)')
    weight_kg = fields.Float(string='Weight (kg)')
    bmi = fields.Float(string='BMI', compute='_compute_bmi', store=True, digits=(5, 2))
    bmi_category = fields.Selection([
        ('underweight', 'Underweight'),
        ('normal', 'Normal'),
        ('overweight', 'Overweight'),
        ('obese', 'Obese'),
    ], compute='_compute_bmi', store=True)
    blood_pressure = fields.Char(string='Blood Pressure')
    vision_left = fields.Char(string='Vision (Left)')
    vision_right = fields.Char(string='Vision (Right)')
    dental_status = fields.Selection([
        ('good', 'Good'),
        ('cavity', 'Cavity'),
        ('gum_issue', 'Gum Issue'),
        ('needs_treatment', 'Needs Treatment'),
        ('other', 'Other'),
    ])
    general_remarks = fields.Text()
    fitness_status = fields.Selection([
        ('fit', 'Fit'),
        ('unfit', 'Unfit'),
        ('needs_attention', 'Needs Attention'),
    ], tracking=True)
    conducted_by = fields.Many2one(
        'hr.employee', string='Conducted By', domain=[('is_health_staff', '=', True)])
    state = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], default='scheduled', tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('op.health.checkup') or _('New')
        return super().create(vals_list)

    @api.depends('height_cm', 'weight_kg')
    def _compute_bmi(self):
        for record in self:
            if record.height_cm and record.weight_kg:
                height_m = record.height_cm / 100.0
                bmi = record.weight_kg / (height_m ** 2)
                record.bmi = bmi
                if bmi < 18.5:
                    record.bmi_category = 'underweight'
                elif bmi < 25:
                    record.bmi_category = 'normal'
                elif bmi < 30:
                    record.bmi_category = 'overweight'
                else:
                    record.bmi_category = 'obese'
            else:
                record.bmi = 0.0
                record.bmi_category = False

    @api.constrains('height_cm', 'weight_kg')
    def _check_positive_measurements(self):
        for record in self:
            if record.height_cm and record.height_cm <= 0:
                raise ValidationError(_('Height must be greater than zero.'))
            if record.weight_kg and record.weight_kg <= 0:
                raise ValidationError(_('Weight must be greater than zero.'))

    def action_complete(self):
        self.write({'state': 'completed'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset(self):
        self.write({'state': 'scheduled'})
