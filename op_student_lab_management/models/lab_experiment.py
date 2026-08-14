# -*- coding: utf-8 -*-
from odoo import models, fields


class LabExperiment(models.Model):
    _name = 'lab.experiment'
    _description = 'Lab Experiment'

    name = fields.Char(string='Experiment Name', required=True)
    code = fields.Char(string='Code')
    subject_id = fields.Many2one('op.subject', string='Subject')
    max_marks = fields.Float(string='Max Marks', default=100.0)
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)
