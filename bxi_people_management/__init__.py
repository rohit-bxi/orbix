# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from . import models


def post_init_hook(env):
    """Teachers that exist before the module is installed get a Teacher ID."""
    env['op.faculty']._bxi_assign_missing_teacher_codes()
