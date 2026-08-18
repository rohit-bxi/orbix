# -*- coding: utf-8 -*-

from odoo import models


class Employee(models.Model):
    _name = 'hr.employee'
    _inherit = ['hr.employee', 'sttl.image.capture.mixin']

    def new_employee_image(self):
        return self.open_image_capture()
