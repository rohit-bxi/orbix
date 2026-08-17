from odoo import fields, models, api


class HealthProfileMixin(models.AbstractModel):
    _name = 'op.health.profile.mixin'
    _description = 'Health Profile Fields'

    chronic_conditions = fields.Text()
    disabilities = fields.Text()
    dietary_restrictions = fields.Text()
    primary_physician = fields.Char()
    physician_contact = fields.Char()
    insurance_provider = fields.Char()
    insurance_policy_no = fields.Char(string='Insurance Policy No.')
    medical_notes = fields.Text(help='Visible to Health Staff only')
    medical_alert = fields.Boolean(compute='_compute_medical_alert', store=True)

    @api.depends('is_allergy', 'chronic_conditions', 'disabilities')
    def _compute_medical_alert(self):
        for record in self:
            record.medical_alert = bool(record.is_allergy or record.chronic_conditions or record.disabilities)
