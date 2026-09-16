from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class HealthPatientMixin(models.AbstractModel):
    _name = 'op.health.patient.mixin'
    _description = 'Health Record Patient Link'

    student_id = fields.Many2one('op.student', string='Student')
    faculty_id = fields.Many2one('op.faculty', string='Teacher')
    patient_type = fields.Selection([
        ('student', 'Student'),
        ('faculty', 'Teacher'),
    ], string='Patient Type', compute='_compute_patient', store=True)
    patient_name = fields.Char(string='Patient Name', compute='_compute_patient', store=True)

    @api.depends('student_id', 'faculty_id')
    def _compute_patient(self):
        for record in self:
            if record.student_id:
                record.patient_type = 'student'
                record.patient_name = record.student_id.name
            elif record.faculty_id:
                record.patient_type = 'faculty'
                record.patient_name = record.faculty_id.name
            else:
                record.patient_type = False
                record.patient_name = False

    @api.constrains('student_id', 'faculty_id')
    def _check_single_patient(self):
        for record in self:
            if bool(record.student_id) == bool(record.faculty_id):
                raise ValidationError(_('Select exactly one patient: either a Student or a Teacher, not both or neither.'))

    @api.model_create_multi
    def create(self, vals_list):
        # student_id/faculty_id have no default, so a create() that omits
        # both never marks them as "stored" and the constrains above would
        # silently skip validating them. Force the check explicitly so a
        # patient-less record can never be created.
        records = super().create(vals_list)
        records._check_single_patient()
        return records
