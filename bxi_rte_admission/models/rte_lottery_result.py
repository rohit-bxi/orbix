# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, models

RESULT_TYPES = [
    ('selected', 'Selected'),
    ('waitlisted', 'Waitlisted'),
    ('not_selected', 'Not Selected'),
]


class RteLotteryResult(models.Model):
    _name = 'rte.lottery.result'
    _description = 'RTE Lottery Result'
    _order = 'rank'

    batch_id = fields.Many2one(
        'rte.lottery.batch', string='Lottery Batch', required=True,
        ondelete='cascade')
    admission_id = fields.Many2one(
        'op.admission', string='Admission', required=True, ondelete='cascade')
    rank = fields.Integer(string='Rank')
    result_type = fields.Selection(
        RESULT_TYPES, string='Result', required=True)
    preference_matched = fields.Integer(
        string='Preference Matched',
        help='Sequence of the school preference that was granted (1 = '
             'first preference).')
