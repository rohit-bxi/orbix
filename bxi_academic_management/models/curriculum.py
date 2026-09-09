# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import _, fields, models


class BxiCurriculum(models.Model):
    _name = 'bxi.curriculum'
    _description = 'Academic Curriculum'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char('Curriculum Name', required=True, tracking=True)
    board_id = fields.Many2one('bxi.board', string='Board', required=True, tracking=True)
    description = fields.Text('Description', required=True)
    class_ids = fields.Many2many('op.course', string='Assigned Classes', tracking=True)
    project_ids = fields.Many2many('bxi.curriculum.project', string='Mapped Projects', tracking=True)
    approval_status = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', required=True, tracking=True)
    locked = fields.Boolean(
        default=False, tracking=True,
        help='A locked curriculum keeps its Board and Assigned Classes read-only, '
             'so teaching already underway against it cannot be reassigned by mistake.')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    _unique_name_board = models.Constraint(
        'unique(name, board_id)',
        'A curriculum with this Name and Board already exists.',
    )

    def action_open_assign_classes(self):
        self.ensure_one()
        view = self.env.ref('bxi_academic_management.view_curriculum_form_assign_classes')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Assign Classes'),
            'res_model': 'bxi.curriculum',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(view.id, 'form')],
            'target': 'current',
        }

    def action_open_map_projects(self):
        self.ensure_one()
        view = self.env.ref('bxi_academic_management.view_curriculum_form_map_projects')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Map Projects'),
            'res_model': 'bxi.curriculum',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(view.id, 'form')],
            'target': 'current',
        }

    def action_approve(self):
        self.write({'approval_status': 'approved'})

    def action_reject(self):
        self.write({'approval_status': 'rejected'})

    def action_reset_to_draft(self):
        self.write({'approval_status': 'draft'})

    def action_toggle_lock(self):
        for curriculum in self:
            curriculum.locked = not curriculum.locked


class BxiCurriculumProject(models.Model):
    _name = 'bxi.curriculum.project'
    _description = 'Curriculum Project (e.g. Science Fair, Math Olympiad)'
    _order = 'name'

    name = fields.Char('Project Name', required=True)
    active = fields.Boolean(default=True)

    _unique_name = models.Constraint(
        'unique(name)',
        'A project with this name already exists.',
    )
