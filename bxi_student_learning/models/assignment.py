# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Homework details the app's Task Details screen shows that OpenEduCat
has no field for: chapter, difficulty, learning objectives and
requirements."""
from odoo import fields, models

DIFFICULTIES = [('easy', 'Easy'), ('medium', 'Medium'), ('hard', 'Hard')]


class OpAssignment(models.Model):
    _inherit = 'op.assignment'

    bxi_chapter = fields.Char('Chapter')
    bxi_difficulty = fields.Selection(DIFFICULTIES, string='Difficulty')
    bxi_learning_objectives = fields.Text('Learning Objectives', help='One objective per line.')
    bxi_requirements = fields.Text('Requirements', help='One requirement per line, e.g. "Submit in PDF format".')
