# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The app's Info page ("About ..."): the school's own words - tagline,
mission, picture, core values and team - edited on the company form."""
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    bxi_about_title = fields.Char('About Title', help='Defaults to "About <school name>".')
    bxi_about_tagline = fields.Char('Tagline')
    bxi_about_mission = fields.Html('Our Mission', sanitize=True)
    bxi_about_image = fields.Image('About Picture', max_width=1600, max_height=1600)
    bxi_about_success_rate = fields.Float(
        'Success Rate (%)', help='Shown with the live student / teacher / parent counts; leave 0 to hide it.')
    bxi_value_ids = fields.One2many('bxi.school.value', 'company_id', string='Core Values')
    bxi_team_member_ids = fields.One2many('bxi.school.team.member', 'company_id', string='Team')


class BxiSchoolValue(models.Model):
    _name = 'bxi.school.value'
    _description = 'School Core Value'
    _order = 'sequence, id'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company,
                                 ondelete='cascade')
    name = fields.Char(required=True, translate=True)
    description = fields.Text(translate=True)
    icon = fields.Char(help='Icon name the app shows, e.g. heart, bolt, shield, globe.')
    sequence = fields.Integer(default=10)


class BxiSchoolTeamMember(models.Model):
    _name = 'bxi.school.team.member'
    _description = 'School Team Member'
    _order = 'sequence, id'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company,
                                 ondelete='cascade')
    name = fields.Char(required=True)
    role = fields.Char(translate=True)
    bio = fields.Text(translate=True)
    image = fields.Image(max_width=512, max_height=512)
    sequence = fields.Integer(default=10)
