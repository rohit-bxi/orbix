# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from . import models


def _create_student_employees(env):
    """Backfill the shadow hr.employee record (used for standard
    kiosk/systray/badge check-in) on every op.student that predates
    this module's install. New students get one automatically via
    op.student.create(). Then brings any OpenEduCat attendance sheet
    history into hr.attendance (see _copy_legacy_op_attendance).
    """
    env['op.student'].search([('employee_id', '=', False)])._ensure_attendance_employee()
    env['hr.attendance']._copy_legacy_op_attendance()
