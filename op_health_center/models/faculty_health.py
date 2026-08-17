from odoo import fields, models, api


class OpFaculty(models.Model):
    _name = 'op.faculty'
    _inherit = ['op.faculty', 'op.health.profile.mixin']

    is_allergy = fields.Boolean(string='Is Allergy')
    allergy = fields.Char(string='Allergy')

    visit_ids = fields.One2many('op.health.visit', 'faculty_id', string='Health Visits')
    vaccination_ids = fields.One2many('op.health.vaccination', 'faculty_id', string='Vaccinations')
    checkup_ids = fields.One2many('op.health.checkup', 'faculty_id', string='Checkups')
    visit_count = fields.Integer(compute='_compute_health_counts')
    vaccination_count = fields.Integer(compute='_compute_health_counts')
    checkup_count = fields.Integer(compute='_compute_health_counts')
    last_checkup_date = fields.Date(compute='_compute_last_checkup_date', store=True)

    @api.depends('visit_ids', 'vaccination_ids', 'checkup_ids')
    def _compute_health_counts(self):
        for record in self:
            record.visit_count = len(record.visit_ids)
            record.vaccination_count = len(record.vaccination_ids)
            record.checkup_count = len(record.checkup_ids)

    @api.depends('checkup_ids.checkup_date', 'checkup_ids.state')
    def _compute_last_checkup_date(self):
        for record in self:
            completed = record.checkup_ids.filtered(lambda c: c.state == 'completed')
            record.last_checkup_date = max(completed.mapped('checkup_date')) if completed else False

    def action_view_health_visits(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Health Visits',
            'res_model': 'op.health.visit',
            'view_mode': 'list,form',
            'domain': [('faculty_id', '=', self.id)],
            'context': {'default_faculty_id': self.id},
        }

    def action_view_vaccinations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Vaccinations',
            'res_model': 'op.health.vaccination',
            'view_mode': 'list,form',
            'domain': [('faculty_id', '=', self.id)],
            'context': {'default_faculty_id': self.id},
        }

    def action_view_checkups(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Checkups',
            'res_model': 'op.health.checkup',
            'view_mode': 'list,form',
            'domain': [('faculty_id', '=', self.id)],
            'context': {'default_faculty_id': self.id},
        }
