# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""
base.res_partner_portal_public_rule is marked noupdate="1" in base's own
data, so a plain <record> override in this module's XML is silently
ignored by the data loader on install/upgrade - only a direct ORM write
(from a hook) actually changes it. Verified during development: without
this, op.student/op.parent (both _inherits res.partner) stay unreadable
to a parent portal user for any child whose contact isn't nested under
the parent's contact in the commercial-partner hierarchy, which blocks
the Parent Portal (and openeducat_parent's own parent login) end-to-end
for any family that doesn't have that contact nesting set up.
"""

PARENT_CHILD_DOMAIN = (
    "['|', ('id', 'child_of', user.commercial_partner_id.id), "
    "('id', 'in', user.child_ids.partner_id.ids)]"
)


def set_parent_portal_partner_rule(env):
    rule = env.ref('base.res_partner_portal_public_rule', raise_if_not_found=False)
    if rule and rule.domain_force != PARENT_CHILD_DOMAIN:
        rule.write({'domain_force': PARENT_CHILD_DOMAIN})
