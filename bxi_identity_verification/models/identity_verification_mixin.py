# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import _, fields, models
from odoo.exceptions import UserError

VERIFICATION_STATUSES = [
    ('unverified', 'Unverified'),
    ('pending', 'Pending Review'),
    ('verified', 'Verified'),
    ('rejected', 'Rejected'),
]


class BxiIdentityVerificationMixin(models.AbstractModel):
    """Shared Aadhaar + face-photo verification state for op.student and
    op.parent. Verification is a human judgment call (comparing a
    submitted ID/photo against the record), so there is no automated
    "verified" transition here - submitting only ever reaches 'pending',
    a staff reviewer moves it to 'verified'/'rejected' from the normal
    Odoo backend form.
    """
    _name = 'bxi.identity.verification.mixin'
    _description = 'Identity Verification Fields'

    aadhar_card = fields.Char(
        string='Aadhaar Number',
        groups='bxi_identity_verification.group_identity_reviewer',
        help='Restricted to Identity Reviewers - other users with read '
             'access to this record do not see this field.')
    aadhar_verification_status = fields.Selection(
        VERIFICATION_STATUSES, string='Aadhaar Status', default='unverified', tracking=True)
    aadhar_submitted_at = fields.Datetime(readonly=True, copy=False)
    aadhar_verified_at = fields.Datetime(readonly=True, copy=False)
    aadhar_verification_notes = fields.Text(string='Aadhaar Review Notes')

    face_verification_status = fields.Selection(
        VERIFICATION_STATUSES, string='Face Photo Status', default='unverified', tracking=True)
    face_submitted_at = fields.Datetime(readonly=True, copy=False)
    face_verified_at = fields.Datetime(readonly=True, copy=False)

    def _submit_aadhar(self, aadhar_number):
        self.ensure_one()
        if not aadhar_number:
            raise UserError(_('An Aadhaar number is required.'))
        self.write({
            'aadhar_card': aadhar_number,
            'aadhar_verification_status': 'pending',
            'aadhar_submitted_at': fields.Datetime.now(),
        })

    def _submit_face(self, image_data):
        self.ensure_one()
        if not image_data:
            raise UserError(_('A captured image is required.'))
        if not self.register_face(image_data):
            raise UserError(_('The captured image could not be saved. Please try again.'))
        self.write({
            'face_verification_status': 'pending',
            'face_submitted_at': fields.Datetime.now(),
        })

    def action_verify_aadhar(self):
        self.write({'aadhar_verification_status': 'verified', 'aadhar_verified_at': fields.Datetime.now()})

    def action_reject_aadhar(self):
        self.write({'aadhar_verification_status': 'rejected'})

    def action_verify_face(self):
        self.write({'face_verification_status': 'verified', 'face_verified_at': fields.Datetime.now()})

    def action_reject_face(self):
        self.write({'face_verification_status': 'rejected'})
