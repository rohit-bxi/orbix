# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Existing teachers get a Teacher ID, oldest first."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['op.faculty']._bxi_assign_missing_teacher_codes()
