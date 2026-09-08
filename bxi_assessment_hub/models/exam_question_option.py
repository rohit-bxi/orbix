# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import api, fields, models


class BxiExamQuestionOption(models.Model):
    _name = 'bxi.exam.question.option'
    _description = 'Exam Question Answer Option'
    _order = 'question_id, sequence, id'
    _rec_name = 'option_text'

    question_id = fields.Many2one(
        'bxi.exam.question', string='Question', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    label = fields.Char(string='Label', compute='_compute_label', store=True)
    option_text = fields.Char(string='Option', required=True)
    is_correct = fields.Boolean(string='Correct Answer')

    @api.depends('sequence', 'question_id.option_ids.sequence')
    def _compute_label(self):
        for option in self:
            siblings = option.question_id.option_ids.sorted('sequence')
            index = list(siblings).index(option) if option in siblings else 0
            option.label = chr(65 + index)
