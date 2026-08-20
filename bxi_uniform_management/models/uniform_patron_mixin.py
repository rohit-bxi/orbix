from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class UniformPatronMixin(models.AbstractModel):
    _name = 'bxi.uniform.patron.mixin'
    _description = 'Uniform Record Patron Link'

    student_id = fields.Many2one('op.student', string='Student')
    faculty_id = fields.Many2one('op.faculty', string='Teacher')
    patron_type = fields.Selection([
        ('student', 'Student'),
        ('faculty', 'Teacher'),
    ], string='Patron Type', compute='_compute_patron', store=True)
    patron_name = fields.Char(string='Patron Name', compute='_compute_patron', store=True)

    @api.depends('student_id', 'faculty_id')
    def _compute_patron(self):
        for record in self:
            if record.student_id:
                record.patron_type = 'student'
                record.patron_name = record.student_id.name
            elif record.faculty_id:
                record.patron_type = 'faculty'
                record.patron_name = record.faculty_id.name
            else:
                record.patron_type = False
                record.patron_name = False

    @api.constrains('student_id', 'faculty_id')
    def _check_single_patron(self):
        for record in self:
            if bool(record.student_id) == bool(record.faculty_id):
                raise ValidationError(_('Select exactly one patron: either a Student or a Teacher, not both or neither.'))
