# -*- coding: utf-8 -*-

from odoo import fields, models


class OpParent(models.Model):
    _name = 'op.parent'
    _inherit = ['op.parent', 'sttl.image.capture.mixin']

    # op.parent has no image_1920 of its own (unlike op.student/op.faculty,
    # which delegate to res.partner via _inherits) -- it only holds a plain
    # Many2one `name` to the linked res.partner. Route the mixin's writes
    # through to that partner so the same "CLICK IMAGE" flow works here too,
    # and so a user later created from this parent (which reuses this same
    # partner_id) picks up the photo automatically via res.users' own
    # _inherits delegation to res.partner -- no separate copy step needed.
    image_1920 = fields.Image(related='name.image_1920', readonly=False, store=True)
