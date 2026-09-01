# -*- coding: utf-8 -*-

from odoo import models


class OpParent(models.Model):
    _name = 'op.parent'
    _inherit = ['op.parent', 'bxi.identity.verification.mixin']
