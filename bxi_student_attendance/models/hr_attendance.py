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

    def _find_matching_session(self, student, check_in):
        """The op.session whose class window a check-in at `check_in` falls
        into, for `student`'s currently running enrollment - or an empty
        recordset if there's no running enrollment or no session covers
        that moment (e.g. no class scheduled that day/period).

        This is what lets the teacher-visibility security rule
        (session_id.faculty_id.user_id) actually match real check-ins:
        without it, kiosk/systray/badge scans never set session_id at all
        and that rule silently matches nothing for any teacher.
        """
        if not (student and check_in):
            return self.env['op.session']
        enrollment = student.course_detail_ids.filtered(lambda line: line.state == 'running')[:1]
        if not enrollment:
            return self.env['op.session']
        sessions = self.env['op.session'].sudo().search([
            ('course_id', '=', enrollment.course_id.id),
            ('batch_id', '=', enrollment.batch_id.id),
            ('session_date', '=', check_in.date()),
        ])
        return sessions.filtered(
            lambda s: s.start_datetime and s.end_datetime and s.start_datetime <= check_in <= s.end_datetime)[:1]

    @api.model_create_multi
    def create(self, vals_list):
        # A row created with a real check_in but no explicit status came
        # through the standard flow (kiosk/systray/badge) for a student
        # shadow employee — that scan itself means "present". Rows a
        # teacher enters by hand for absence/lateness always pass
        # `status` explicitly and are left untouched.
        employee_ids = {vals['employee_id'] for vals in vals_list if vals.get('employee_id')}
        student_employees = self.env['hr.employee']
        if employee_ids:
            # .exists() first: a stale/invalid device-supplied employee_id must fall through to
            # the normal FK validation in super().create() with a clean error, not crash here.
            student_employees = self.env['hr.employee'].browse(employee_ids).exists().filtered('student_id')
        student_employee_map = {employee.id: employee for employee in student_employees}
        for vals in vals_list:
            employee = student_employee_map.get(vals.get('employee_id'))
            if not employee:
                continue
            if 'status' not in vals:
                vals['status'] = 'present'
            if not vals.get('session_id') and vals.get('check_in'):
                check_in = fields.Datetime.to_datetime(vals['check_in'])
                session = self._find_matching_session(employee.student_id, check_in)
                if session:
                    vals['session_id'] = session.id
        return super().create(vals_list)
