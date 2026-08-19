from odoo import api, fields, models


class BxiTimetable(models.Model):
    _name = 'bxi.timetable'
    _description = 'Class Timetable'
    _rec_name = 'display_name'

    course_id = fields.Many2one('op.course', string='Class', required=True)
    batch_id = fields.Many2one('op.batch', string='Section', required=True,
                                domain="[('course_id', '=', course_id)]")
    locked = fields.Boolean(default=False)
    line_ids = fields.One2many('bxi.timetable.line', 'timetable_id', string='Periods')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    _unique_course_batch = models.Constraint(
        'unique(course_id, batch_id)',
        'A timetable already exists for this Class and Section.',
    )

    @api.depends('course_id', 'batch_id')
    def _compute_display_name(self):
        for timetable in self:
            timetable.display_name = '%s - %s' % (
                timetable.course_id.name or '', timetable.batch_id.name or '')

    def action_lock(self):
        self.locked = True

    def action_unlock(self):
        self.locked = False

    @api.model
    def _get_or_create(self, course_id, batch_id):
        timetable = self.search([('course_id', '=', course_id), ('batch_id', '=', batch_id)], limit=1)
        return timetable or self.create({'course_id': course_id, 'batch_id': batch_id})
