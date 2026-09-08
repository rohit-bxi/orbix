# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import models


class OpParent(models.Model):
    _name = 'op.parent'
    _inherit = ['op.parent', 'bxi.identity.verification.mixin']
