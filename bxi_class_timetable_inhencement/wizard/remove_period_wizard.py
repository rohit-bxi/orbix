from odoo import api, fields, models


class BxiRemovePeriodWizard(models.TransientModel):
    _name = 'bxi.remove.period.wizard'
    _description = 'Remove Teaching Period'

    line_id = fields.Many2one('bxi.timetable.line', required=True)
    day = fields.Selection(related='line_id.day', readonly=True)
    timing_id = fields.Many2one(related='line_id.timing_id', readonly=True)
    subject_id = fields.Many2one(related='line_id.subject_id', readonly=True)
    class_section = fields.Char(compute='_compute_class_section')

    @api.depends('line_id')
    def _compute_class_section(self):
        for wizard in self:
            wizard.class_section = wizard.line_id.timetable_id.display_name

    def action_remove_period(self):
        self.ensure_one()
        self.line_id.unlink()
