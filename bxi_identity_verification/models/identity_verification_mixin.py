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

    # Scanned ID proof (image or PDF) uploaded by the school office. The
    # attachments themselves live in an `id_document_ids` many2many each
    # concrete model declares with its own relation table.
    id_document_status = fields.Selection(
        VERIFICATION_STATUSES, string='ID Document Status', default='unverified', tracking=True)
    id_document_type = fields.Selection([
        ('aadhaar', 'Aadhaar Card'),
        ('pan', 'PAN Card'),
        ('passport', 'Passport'),
        ('driving_licence', 'Driving Licence'),
        ('voter_id', 'Voter ID'),
        ('birth_certificate', 'Birth Certificate'),
        ('other', 'Other'),
    ], string='ID Document Type')
    id_document_submitted_at = fields.Datetime(readonly=True, copy=False)
    id_document_verified_at = fields.Datetime(readonly=True, copy=False)
    id_document_notes = fields.Text(string='ID Document Review Notes')

    def _submit_id_documents(self, files, doc_type=False):
        """Attach uploaded ID proof - [{name, content (bytes), mimetype}] -
        and send it for review. Earlier ID documents are replaced."""
        self.ensure_one()
        if not files:
            raise UserError(_('An ID document is required.'))
        Attachment = self.env['ir.attachment'].sudo()
        attachments = Attachment
        for file in files:
            attachments |= Attachment.create({
                'name': file.get('name') or 'id-document',
                'raw': file['content'],
                'mimetype': file.get('mimetype') or False,
                'res_model': self._name,
                'res_id': self.id,
            })
        old = self.id_document_ids
        self.write({
            'id_document_ids': [(6, 0, attachments.ids)],
            'id_document_type': doc_type or self.id_document_type or False,
            'id_document_status': 'pending',
            'id_document_submitted_at': fields.Datetime.now(),
            'id_document_verified_at': False,
        })
        (old - attachments).sudo().unlink()
        return attachments

    def action_verify_id_document(self):
        self.write({'id_document_status': 'verified', 'id_document_verified_at': fields.Datetime.now()})

    def action_reject_id_document(self):
        self.write({'id_document_status': 'rejected'})

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
