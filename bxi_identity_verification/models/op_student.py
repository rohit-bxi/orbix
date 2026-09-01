# -*- coding: utf-8 -*-

from odoo import models


class OpStudent(models.Model):
    _name = 'op.student'
    _inherit = ['op.student', 'bxi.identity.verification.mixin']
