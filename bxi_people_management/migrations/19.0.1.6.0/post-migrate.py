# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """The Link Student screen's relationships exist on upgraded databases
    too. Existing links need no rows: without one, a parent's own
    relationship applies to every linked student."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['op.parent.relationship']._bxi_ensure_defaults()
