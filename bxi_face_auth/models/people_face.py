# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Face Recognition on the back-office Teacher, Student and Parent forms
(Account & Security tab): the account's face-login state, and Enable (with
the person's latest photo) / Disable buttons. Uses the same service as the
people API's "face" block."""
from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.bxi_api_support.models.people_account import check_manager
from odoo.addons.bxi_api_support.models.people_service import PeopleError

FACE_STATES = [
    ('none', 'Not Enabled'),
    ('pending', 'Pending Review'),
    ('active', 'Active'),
    ('rejected', 'Rejected'),
    ('expired', 'Expired'),
]


class BxiPeopleAccountMixin(models.AbstractModel):
    _inherit = 'bxi.people.account.mixin'

    bxi_face_state = fields.Selection(
        FACE_STATES, string='Face Recognition', compute='_compute_bxi_face',
        help='Face scan for sign-in and attendance, on this person\'s login.')
    bxi_face_enrolled_at = fields.Datetime(string='Face Enrolled On', compute='_compute_bxi_face')
    bxi_face_expires_at = fields.Datetime(string='Face Expires On', compute='_compute_bxi_face')
    bxi_face_problem = fields.Char(string='Face Photo Problem', compute='_compute_bxi_face')

    def _compute_bxi_face(self):
        Enrolment = self.env['bxi.face.enrolment'].sudo()
        for record in self:
            user = record.user_id.sudo()
            state, active, problem = 'none', Enrolment, False
            if user:
                enrolments = Enrolment.search([('user_id', '=', user.id)], order='id desc')
                active = enrolments.filtered(lambda e: e.state == 'active')[:1]
                latest = enrolments[:1]
                if active:
                    state = 'active'
                elif enrolments.filtered(lambda e: e.state == 'pending'):
                    state = 'pending'
                elif latest.state == 'rejected':
                    state, problem = 'rejected', latest.reject_reason or False
                elif latest.state == 'expired' and latest.end_reason == 'validity period ended':
                    state = 'expired'
                problem = problem or user.bxi_face_photo_error or False
            record.bxi_face_state = state
            record.bxi_face_enrolled_at = active.activated_at if active else False
            record.bxi_face_expires_at = active.expires_at if active else False
            record.bxi_face_problem = problem

    def action_bxi_face_enable(self):
        self.ensure_one()
        check_manager(self.env)
        if not self.user_id:
            raise UserError(_('Create a login first: face recognition signs in to an account.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Enable Face Recognition'),
            'res_model': 'bxi.face.enable.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_res_model': self._name, 'default_res_id': self.id},
        }

    def action_bxi_face_disable(self):
        self.ensure_one()
        check_manager(self.env)
        user = self.user_id.sudo()
        if not user:
            raise UserError(_('This person has no login yet.'))
        try:
            self.env['bxi.people.service']._apply_face(self, user, {'enabled': False})
        except PeopleError as exc:
            raise UserError(exc.to_text()) from None


class BxiFaceEnableWizard(models.TransientModel):
    _name = 'bxi.face.enable.wizard'
    _description = 'Enable Face Recognition'

    res_model = fields.Selection(
        [('op.student', 'Student'), ('op.faculty', 'Teacher'), ('op.parent', 'Parent')], required=True)
    res_id = fields.Integer(required=True)
    image = fields.Binary(string='Latest Photo', required=True,
                          help='A clear, recent photo of the face, looking straight at the camera.')
    consent_reference = fields.Char(
        string='Parent Consent Form No.',
        help="For students: the number of the parent's signed consent form, when the school requires consent.")

    def action_apply(self):
        self.ensure_one()
        check_manager(self.env)
        record = self.env[self.res_model].sudo().with_context(active_test=False).browse(self.res_id).exists()
        if not record:
            raise UserError(_('This person no longer exists.'))
        user = record.user_id.sudo()
        if not user:
            raise UserError(_('Create a login first: face recognition signs in to an account.'))
        image = self.image.decode() if isinstance(self.image, bytes) else self.image
        face = {'enabled': True, 'image': image}
        if self.consent_reference:
            face['consent_reference'] = self.consent_reference
        try:
            self.env['bxi.people.service']._apply_face(record, user, face)
        except PeopleError as exc:
            raise UserError(exc.to_text()) from None
        return {'type': 'ir.actions.act_window_close'}

