# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The relationship of a parent to each linked student (the app's Link
Student screen): Sanjay can be Father of Aarav and Guardian of Madhav.

Which students a parent has stays op.parent.student_ids (used everywhere
in OpenEduCat and the portals). A link row only records a relationship
that differs from - or was set apart from - the parent's own
relationship_id, which remains the parent's main relationship (shown on
the profile). Without a row, the parent's relationship applies."""
from odoo import api, fields, models

# The relationships the Link Student screen offers. "Gaurdian" is how the
# OpenEduCat demo data spells it.
DEFAULT_RELATIONSHIPS = ('Mother', 'Father', 'Guardian', 'Grandparents', 'Other')
_MISSPELLED = {'Guardian': ('Gaurdian',)}


class BxiParentStudentLink(models.Model):
    _name = 'bxi.parent.student.link'
    _description = 'Parent - Student Relationship'
    _rec_name = 'student_id'

    parent_id = fields.Many2one('op.parent', required=True, ondelete='cascade', index=True)
    student_id = fields.Many2one('op.student', required=True, ondelete='cascade', index=True)
    relationship_id = fields.Many2one('op.parent.relationship', string='Relationship', required=True,
                                      ondelete='restrict')

    _unique_parent_student = models.Constraint(
        'unique(parent_id, student_id)', 'A parent has one relationship with each student.')


class OpParentRelationship(models.Model):
    _inherit = 'op.parent.relationship'

    @api.model
    def _bxi_ensure_defaults(self):
        """Create the screen's relationships that are missing (matching
        names case-insensitively, and renaming the demo's misspelling)."""
        for name in DEFAULT_RELATIONSHIPS:
            if self.search([('name', '=ilike', name)], limit=1):
                continue
            for wrong in _MISSPELLED.get(name, ()):
                misspelled = self.search([('name', '=ilike', wrong)], limit=1)
                if misspelled:
                    misspelled.name = name
                    break
            else:
                self.create({'name': name})


class OpParent(models.Model):
    _inherit = 'op.parent'

    bxi_student_link_ids = fields.One2many(
        'bxi.parent.student.link', 'parent_id', string='Relationship per Student',
        help='Where this parent is something else to a student than their main relationship '
             '(e.g. Guardian of a nephew).')

    def _bxi_relationship_for(self, student):
        """This parent's relationship with `student`."""
        self.ensure_one()
        link = self.sudo().bxi_student_link_ids.filtered(lambda l: l.student_id == student)[:1]
        return link.relationship_id or self.relationship_id

    def _bxi_set_relationship(self, student, relationship):
        """Record `relationship` for `student`: the parent's main
        relationship when it has none yet, else a link row when it
        differs."""
        self.ensure_one()
        parent = self.sudo()
        link = parent.bxi_student_link_ids.filtered(lambda l: l.student_id == student)[:1]
        if not parent.relationship_id:
            parent.relationship_id = relationship
            link.unlink()
        elif relationship == parent.relationship_id:
            link.unlink()
        elif link:
            link.relationship_id = relationship
        else:
            self.env['bxi.parent.student.link'].sudo().create({
                'parent_id': parent.id, 'student_id': student.id, 'relationship_id': relationship.id})

    def _bxi_drop_stale_links(self):
        """Forget the relationship with students no longer linked."""
        for parent in self.sudo().with_context(active_test=False):
            parent.bxi_student_link_ids.filtered(lambda l: l.student_id not in parent.student_ids).unlink()

    def write(self, vals):
        res = super().write(vals)
        if 'student_ids' in vals:
            self._bxi_drop_stale_links()
        return res


class OpStudent(models.Model):
    _inherit = 'op.student'

    def write(self, vals):
        parents = self.with_context(active_test=False).parent_ids if 'parent_ids' in vals else None
        res = super().write(vals)
        if parents is not None:
            parents._bxi_drop_stale_links()
        return res
