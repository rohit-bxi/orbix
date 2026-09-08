# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, models


class BxiMessage(models.Model):
    _name = 'bxi.message'
    _description = 'Parent-Teacher Message'
    _order = 'create_date asc'

    thread_id = fields.Many2one('bxi.message.thread', required=True, index=True, ondelete='cascade')
    sender_user_id = fields.Many2one('res.users', required=True, index=True)
    body = fields.Text(required=True)
    read_at = fields.Datetime(readonly=True, copy=False)
