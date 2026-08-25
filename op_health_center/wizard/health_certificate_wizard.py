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
            course_detail = patient.course_detail_ids.filtered(lambda c: c.state == 'running')[:1]
            reg_no = patient.gr_no
            affiliation = course_detail.course_id.name if course_detail else ''
        else:
            checkup_domain.append(('faculty_id', '=', patient.id))
            vaccination_domain.append(('faculty_id', '=', patient.id))
            reg_no = patient.id_number
            affiliation = patient.main_department_id.name or ''
        if self.date_from:
            vaccination_domain.append(('date_administered', '>=', self.date_from))
        if self.date_to:
            vaccination_domain.append(('date_administered', '<=', self.date_to))

        latest_checkup = self.env['op.health.checkup'].search(checkup_domain, order='checkup_date desc', limit=1)
        vaccinations = self.env['op.health.vaccination'].search(vaccination_domain, order='date_administered')

        today = fields.Date.context_today(self)
        age = None
        if patient.birth_date:
            age = today.year - patient.birth_date.year - (
                (today.month, today.day) < (patient.birth_date.month, patient.birth_date.day))

        datas = {
            'certificate_no': certificate_no,
            'certificate_date': today,
            'certificate_type': self.certificate_type,
            'certificate_type_label': dict(self._fields['certificate_type'].selection).get(self.certificate_type),
            'patient_type': self.patient_type,
            'patient_type_label': dict(self._fields['patient_type'].selection).get(self.patient_type),
            'patient_name': patient.name,
            'patient_gender': dict(patient._fields['gender'].selection).get(patient.gender) if patient.gender else '',
            'patient_age': age,
            'patient_reg_no': reg_no or '',
            'patient_affiliation': affiliation,
            'blood_group': patient.blood_group,
            'is_allergy': patient.is_allergy,
            'allergy': patient.allergy,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'latest_checkup': {
                'checkup_date': latest_checkup.checkup_date,
                'height_cm': latest_checkup.height_cm,
                'weight_kg': latest_checkup.weight_kg,
                'bmi': latest_checkup.bmi,
                'bmi_category': dict(latest_checkup._fields['bmi_category'].selection).get(latest_checkup.bmi_category) if latest_checkup.bmi_category else '',
                'blood_pressure': latest_checkup.blood_pressure,
                'vision_left': latest_checkup.vision_left,
                'vision_right': latest_checkup.vision_right,
                'dental_status': dict(latest_checkup._fields['dental_status'].selection).get(latest_checkup.dental_status) if latest_checkup.dental_status else '',
                'fitness_status': latest_checkup.fitness_status,
                'fitness_status_label': dict(latest_checkup._fields['fitness_status'].selection).get(latest_checkup.fitness_status) if latest_checkup.fitness_status else '',
                'general_remarks': latest_checkup.general_remarks,
                'conducted_by': latest_checkup.conducted_by.name or '',
            } if latest_checkup else False,
            'vaccinations': [{
                'vaccine_name': vac.vaccine_id.name,
                'dose_number': vac.dose_number,
                'date_administered': vac.date_administered,
                'batch_no': vac.batch_no,
                'next_due_date': vac.next_due_date,
                'administered_by': vac.administered_by.name or '',
            } for vac in vaccinations],
        }
        return self.env.ref('op_health_center.action_report_health_certificate').report_action(self, data=datas)
