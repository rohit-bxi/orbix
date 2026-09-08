# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import fields, models


class OpStudentFeeWaiver(models.Model):
    """A single waiver credit applied to one fee line, created by an
    approved bxi.fee.exemption or bxi.student.scholarship grant. Kept as
    its own ledger - rather than a plain amount field on
    op.student.fees.details - so a waiver stays traceable to the grant
    that produced it and disappears cleanly (via ondelete=cascade / the
    granting module's own sync method) if that grant is later
    rejected or reset to draft.
    """
    _name = 'op.student.fee.waiver'
    _description = 'Student Fee Waiver'

    # source_ref deliberately uses fields.Reference rather than two
    # module-specific Many2one fields: bxi_fee_management does not (and
    # should not) depend on bxi_fee_exemption_management or
    # bxi_school_scholarship, so a Many2one to either of those models
    # would break installing this module without them. A Reference just
    # stores "model,id" as text with no FK, so the grantor module stays
    # free to not be installed.
    detail_id = fields.Many2one(
        'op.student.fees.details', string='Fee Line', required=True,
        ondelete='cascade', index=True)
    source = fields.Selection([
        ('exemption', 'Fee Exemption'),
        ('scholarship', 'Scholarship'),
    ], required=True)
    source_ref = fields.Reference(
        selection=[
            ('bxi.fee.exemption', 'Fee Exemption'),
            ('bxi.student.scholarship', 'Scholarship'),
        ], string='Granted By', required=True)
    amount = fields.Monetary(required=True)
    currency_id = fields.Many2one(related='detail_id.currency_id')

    _unique_source_per_detail = models.Constraint(
        'unique(detail_id, source_ref)',
        'This grant already has a waiver recorded on this fee line.')
