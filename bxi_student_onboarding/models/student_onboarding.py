# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

STEP_ORDER = ['basic_info', 'academic_info', 'documents', 'done']


class BxiStudentOnboarding(models.Model):
    _name = 'bxi.student.onboarding'
    _description = 'Student Onboarding'
    _inherit = ['sttl.image.capture.mixin', 'mail.thread', 'mail.activity.mixin']
    _rec_name = 'full_name'
    _order = 'id desc'

    state = fields.Selection([
        ('basic_info', 'Basic Information'),
        ('academic_info', 'Academic Details'),
        ('documents', 'Upload Documents'),
        ('done', 'Completed'),
    ], string='Step', default='basic_info', copy=False, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    # Step 1 - Basic Information
    image_1920 = fields.Image('Photo')
    full_name = fields.Char('Full Name', tracking=True)
    gender = fields.Selection([
        ('m', 'Male'),
        ('f', 'Female'),
        ('o', 'Other'),
    ], string='Gender')
    birth_date = fields.Date('Date of Birth')
    email = fields.Char('Email Address')
    phone = fields.Char('Phone Number')
    blood_group = fields.Selection([
        ('A+', 'A+ve'),
        ('B+', 'B+ve'),
        ('O+', 'O+ve'),
        ('AB+', 'AB+ve'),
        ('A-', 'A-ve'),
        ('B-', 'B-ve'),
        ('O-', 'O-ve'),
        ('AB-', 'AB-ve'),
    ], string='Blood Group')
    nationality = fields.Many2one('res.country', 'Nationality')
    street = fields.Char('Street')
    street2 = fields.Char('Street2')
    city = fields.Char('City')
    state_id = fields.Many2one('res.country.state', 'State',
                               domain="[('country_id', '=', country_id)]")
    zip = fields.Char('Zip')
    country_id = fields.Many2one('res.country', 'Country')

    # Step 2 - Academic Details
    admission_number = fields.Char(
        'Admission Number', copy=False, tracking=True, readonly=True)
    admission_date = fields.Date('Admission Date', default=fields.Date.context_today)
    course_id = fields.Many2one('op.course', 'Class', tracking=True)
    batch_id = fields.Many2one('op.batch', 'Section', tracking=True,
                               domain="[('course_id', '=', course_id)]")
    roll_number = fields.Char('Roll Number')
    enrollment_status = fields.Selection([
        ('new_admission', 'New Admission'),
        ('active', 'Active'),
        ('transferred', 'Transferred'),
        ('alumni', 'Alumni'),
        ('dropped', 'Dropped'),
    ], string='Status', default='new_admission', tracking=True)
    parent_id = fields.Many2one(
        'op.parent', 'Parent/Guardian', tracking=True,
        help='Search to link an existing parent, or use "Create and edit..." '
             'to add a new Parent/Guardian.')

    # Step 3 - Upload Documents
    medical_record_ids = fields.Many2many(
        comodel_name='ir.attachment',
        relation='bxi_onboarding_medical_record_rel',
        column1='onboarding_id', column2='attachment_id',
        string='Medical Records')
    birth_certificate_ids = fields.Many2many(
        comodel_name='ir.attachment',
        relation='bxi_onboarding_birth_certificate_rel',
        column1='onboarding_id', column2='attachment_id',
        string='Birth Certificate')
    transfer_certificate_ids = fields.Many2many(
        comodel_name='ir.attachment',
        relation='bxi_onboarding_transfer_certificate_rel',
        column1='onboarding_id', column2='attachment_id',
        string='Transfer Certificate')
    previous_school_certificate_ids = fields.Many2many(
        comodel_name='ir.attachment',
        relation='bxi_onboarding_prev_school_cert_rel',
        column1='onboarding_id', column2='attachment_id',
        string='Previous School Certificate')

    # Result
    student_id = fields.Many2one('op.student', 'Student', readonly=True,
                                 copy=False, tracking=True)

    _unique_admission_number = models.Constraint(
        'unique(admission_number)',
        'Admission Number must be unique per onboarding record!')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('admission_number'):
                vals['admission_number'] = self.env['ir.sequence'].next_by_code(
                    'bxi.student.onboarding.admission') or '/'
        return super().create(vals_list)

    @api.onchange('course_id')
    def _onchange_course_id(self):
        self.batch_id = False

    def _check_required(self, fields_map):
        missing = [label for fname, label in fields_map.items() if not self[fname]]
        if missing:
            raise ValidationError(_(
                'Please fill in the following required field(s): %s'
            ) % ', '.join(missing))

    def action_next(self):
        self.ensure_one()
        if self.state == 'basic_info':
            self._check_required({
                'full_name': _('Full Name'),
                'gender': _('Gender'),
                'birth_date': _('Date of Birth'),
                'email': _('Email Address'),
            })
            self.state = 'academic_info'
        elif self.state == 'academic_info':
            self._check_required({
                'admission_number': _('Admission Number'),
                'admission_date': _('Admission Date'),
                'course_id': _('Class'),
                'batch_id': _('Section'),
                'enrollment_status': _('Status'),
            })
            self.state = 'documents'

    def action_back(self):
        self.ensure_one()
        index = STEP_ORDER.index(self.state)
        if index > 0:
            self.state = STEP_ORDER[index - 1]

    def _get_student_vals(self):
        self.ensure_one()
        name_parts = (self.full_name or '').split()
        first_name = name_parts[0] if name_parts else ''
        last_name = name_parts[-1] if len(name_parts) > 1 else ''
        middle_name = ' '.join(name_parts[1:-1]) if len(name_parts) > 2 else ''

        vals = {
            'first_name': first_name,
            'middle_name': middle_name,
            'last_name': last_name,
            'gender': self.gender,
            'birth_date': self.birth_date,
            'email': self.email,
            'phone': self.phone,
            'blood_group': self.blood_group,
            'nationality': self.nationality.id,
            'street': self.street,
            'street2': self.street2,
            'city': self.city,
            'state_id': self.state_id.id,
            'zip': self.zip,
            'country_id': self.country_id.id,
            'image_1920': self.image_1920,
            'gr_no': self.admission_number,
            'admission_date': self.admission_date,
            'enrollment_status': self.enrollment_status,
            'course_detail_ids': [(0, 0, {
                'course_id': self.course_id.id,
                'batch_id': self.batch_id.id,
                'roll_number': self.roll_number,
            })],
            'medical_record_ids': [(6, 0, self.medical_record_ids.ids)],
            'birth_certificate_ids': [(6, 0, self.birth_certificate_ids.ids)],
            'transfer_certificate_ids': [(6, 0, self.transfer_certificate_ids.ids)],
            'previous_school_certificate_ids':
                [(6, 0, self.previous_school_certificate_ids.ids)],
        }
        if self.parent_id:
            vals['parent_ids'] = [(6, 0, [self.parent_id.id])]
        return vals

    def action_complete_onboarding(self):
        self.ensure_one()
        if self.student_id:
            raise ValidationError(_('This onboarding is already completed.'))
        self.student_id = self.env['op.student'].create(self._get_student_vals())
        self.state = 'done'

    def action_view_student(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Student'),
            'res_model': 'op.student',
            'view_mode': 'form',
            'res_id': self.student_id.id,
            'target': 'current',
        }
