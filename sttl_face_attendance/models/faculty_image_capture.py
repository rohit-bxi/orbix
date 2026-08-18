# -*- coding: utf-8 -*-

from odoo import models


class OpFaculty(models.Model):
    _name = 'op.faculty'
    _inherit = ['op.faculty', 'sttl.image.capture.mixin']
