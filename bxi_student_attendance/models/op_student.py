from odoo import api, fields, models


class OpStudent(models.Model):
    _inherit = 'op.student'

    employee_id = fields.Many2one(
        'hr.employee', string='Attendance Employee', copy=False, readonly=True,
        help='Lightweight shadow employee record used only so this '
             'student can check in/out through the standard Attendances '
             'kiosk/systray/badge flow. Carries no payroll/contract data.')

    @api.model_create_multi
    def create(self, vals_list):
        students = super().create(vals_list)
        students._ensure_attendance_employee()
        return students

    def _ensure_attendance_employee(self):
        """Create the shadow hr.employee backing this student's
        attendance identity, if it doesn't exist yet.

        sudo() because creating an hr.employee record isn't something
        the acting user (e.g. admissions staff creating a student)
        necessarily has rights to do directly, and this is bookkeeping
        the student's own record needs regardless of who created it.
        """
        Employee = self.env['hr.employee'].sudo()
        for student in self:
            if student.employee_id:
                continue
            employee = Employee.create({
                'name': student.name,
                'student_id': student.id,
                'employee_type': 'student',
                'company_id': self.env.company.id,
            })
            student.employee_id = employee.id
