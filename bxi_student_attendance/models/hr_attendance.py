from odoo import api, fields, models


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    # Only rows created for absence/lateness bookkeeping (no real scan
    # happened) go through this model without a check_in; standard
    # kiosk/systray/badge check-ins always supply one via the base flow.
    check_in = fields.Datetime(required=False)

    student_id = fields.Many2one(
        'op.student', string='Student', related='employee_id.student_id',
        store=True, index=True)
    class_id = fields.Many2one(
        'op.course', string='Class', compute='_compute_class_section',
        store=True, index=True)
    section_id = fields.Many2one(
        'op.batch', string='Section', compute='_compute_class_section',
        store=True, index=True)
    session_id = fields.Many2one(
        'op.session', string='Period', ondelete='cascade', index=True)
    status = fields.Selection([
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('excused', 'Excused'),
    ], string='Attendance Status')
    remark = fields.Char('Comment')

    _unique_student_session = models.Constraint(
        'unique(student_id, session_id)',
        'Attendance for this student on this period already exists.')

    @api.depends('student_id', 'student_id.course_detail_ids.state')
    def _compute_class_section(self):
        for attendance in self:
            enrollment = attendance.student_id.course_detail_ids.filtered(
                lambda line: line.state == 'running')[:1]
            attendance.class_id = enrollment.course_id
            attendance.section_id = enrollment.batch_id

    @api.model_create_multi
    def create(self, vals_list):
        # A row created with a real check_in but no explicit status came
        # through the standard flow (kiosk/systray/badge) for a student
        # shadow employee — that scan itself means "present". Rows a
        # teacher enters by hand for absence/lateness always pass
        # `status` explicitly and are left untouched.
        employee_ids = {vals['employee_id'] for vals in vals_list if vals.get('employee_id')}
        student_employee_ids = set()
        if employee_ids:
            student_employee_ids = set(self.env['hr.employee'].browse(employee_ids).filtered('student_id').ids)
        for vals in vals_list:
            if 'status' not in vals and vals.get('employee_id') in student_employee_ids:
                vals['status'] = 'present'
        return super().create(vals_list)
