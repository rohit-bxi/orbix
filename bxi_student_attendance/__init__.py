from . import models


def _create_student_employees(env):
    """Backfill the shadow hr.employee record (used for standard
    kiosk/systray/badge check-in) on every op.student that predates
    this module's install. New students get one automatically via
    op.student.create().
    """
    env['op.student'].search([('employee_id', '=', False)])._ensure_attendance_employee()
