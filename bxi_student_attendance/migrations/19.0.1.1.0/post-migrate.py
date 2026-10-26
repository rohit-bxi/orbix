# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """hr.attendance became the only attendance store the portal and the
    mobile app read - bring the OpenEduCat sheet history across once."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.attendance']._copy_legacy_op_attendance()
