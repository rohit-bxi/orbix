from odoo import fields, models


class HealthCertificateWizard(models.TransientModel):
    _name = 'op.health.certificate.wizard'
    _description = 'Print Medical Certificate'

    patient_type = fields.Selection([
        ('student', 'Student'),
        ('faculty', 'Teacher'),
    ], required=True, default='student')
    student_id = fields.Many2one('op.student', string='Student')
    faculty_id = fields.Many2one('op.faculty', string='Teacher')
    certificate_type = fields.Selection([
        ('fitness', 'Fitness Certificate'),
        ('vaccination', 'Vaccination Certificate'),
        ('general', 'General Medical Certificate'),
    ], required=True, default='general')
    date_from = fields.Date(string='Date From')
    date_to = fields.Date(string='Date To')

    def print_certificate(self):
        patient = self.student_id if self.patient_type == 'student' else self.faculty_id
        certificate_no = self.env['ir.sequence'].next_by_code('op.health.certificate')

        checkup_domain = [('state', '=', 'completed')]
        vaccination_domain = [('state', '=', 'completed')]
        if self.patient_type == 'student':
            checkup_domain.append(('student_id', '=', patient.id))
            vaccination_domain.append(('student_id', '=', patient.id))
        else:
            checkup_domain.append(('faculty_id', '=', patient.id))
            vaccination_domain.append(('faculty_id', '=', patient.id))
        if self.date_from:
            vaccination_domain.append(('date_administered', '>=', self.date_from))
        if self.date_to:
            vaccination_domain.append(('date_administered', '<=', self.date_to))

        latest_checkup = self.env['op.health.checkup'].search(checkup_domain, order='checkup_date desc', limit=1)
        vaccinations = self.env['op.health.vaccination'].search(vaccination_domain, order='date_administered')

        datas = {
            'certificate_no': certificate_no,
            'certificate_date': fields.Date.context_today(self),
            'certificate_type': dict(self._fields['certificate_type'].selection).get(self.certificate_type),
            'patient_name': patient.name,
            'blood_group': patient.blood_group,
            'latest_checkup': {
                'checkup_date': latest_checkup.checkup_date,
                'height_cm': latest_checkup.height_cm,
                'weight_kg': latest_checkup.weight_kg,
                'bmi': latest_checkup.bmi,
                'fitness_status': dict(latest_checkup._fields['fitness_status'].selection).get(latest_checkup.fitness_status) if latest_checkup.fitness_status else '',
                'general_remarks': latest_checkup.general_remarks,
            } if latest_checkup else False,
            'vaccinations': [{
                'vaccine_name': vac.vaccine_id.name,
                'dose_number': vac.dose_number,
                'date_administered': vac.date_administered,
            } for vac in vaccinations],
        }
        return self.env.ref('op_health_center.action_report_health_certificate').report_action(self, data=datas)
