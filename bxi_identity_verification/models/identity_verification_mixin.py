# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .aadhaar import AadhaarInUseError, aadhaar_hash, clean_aadhaar, mask_aadhaar, normalize_aadhaar

# The people records an Aadhaar number can sit on. One number belongs to
# one person: it may appear on several of these records only when they are
# the same person (same login or same contact).
AADHAAR_MODELS = ('op.student', 'op.faculty', 'op.parent')

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
        string='Aadhaar Number', copy=False,
        groups='bxi_identity_verification.group_identity_reviewer',
        help='Restricted to Identity Reviewers - other users with read '
             'access to this record do not see this field. Saved as 12 '
             'digits; a number typed by the school office counts as verified.')
    bxi_aadhaar_hash = fields.Char(
        compute='_compute_bxi_aadhaar', store=True, index=True, copy=False,
        groups='base.group_system',
        help='Keyed hash of the Aadhaar number, used to look the number up (e.g. Aadhaar login) '
             'without a searchable plain copy.')
    bxi_aadhaar_last4 = fields.Char(
        string='Aadhaar Last 4 Digits', compute='_compute_bxi_aadhaar', store=True, copy=False)
    bxi_aadhaar_masked = fields.Char(string='Aadhaar', compute='_compute_bxi_aadhaar_masked')
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

    # -- Aadhaar number ------------------------------------------------------------

    @api.depends('aadhar_card')
    def _compute_bxi_aadhaar(self):
        for record in self:
            digits = normalize_aadhaar(record.sudo().aadhar_card)
            record.bxi_aadhaar_hash = aadhaar_hash(self.env, digits) if digits else False
            record.bxi_aadhaar_last4 = digits[-4:] if digits else False

    @api.depends('bxi_aadhaar_last4')
    def _compute_bxi_aadhaar_masked(self):
        for record in self:
            record.bxi_aadhaar_masked = mask_aadhaar(record.bxi_aadhaar_last4) or False

    def _bxi_aadhaar_partner(self):
        """The contact of this person (op.parent overrides: its `name`)."""
        self.ensure_one()
        return self.partner_id if 'partner_id' in self._fields else self.env['res.partner']

    def _bxi_same_person(self, other):
        """True when `other` (a record of an AADHAAR_MODELS model) is the
        same person as this record: same login, or same contact."""
        self.ensure_one()
        if self._name == other._name and self.id == other.id:
            return True
        user, other_user = self.sudo().user_id, other.sudo().user_id
        if user and other_user:
            return user == other_user
        partner, other_partner = self._bxi_aadhaar_partner(), other._bxi_aadhaar_partner()
        return bool(partner) and partner == other_partner

    @api.model
    def _bxi_aadhaar_holders(self, digits):
        """Every student/teacher/parent record (archived ones included)
        holding the normalized Aadhaar number `digits`."""
        hashed = aadhaar_hash(self.env, digits)
        holders = []
        for model in AADHAAR_MODELS:
            if model in self.env:
                holders.extend(self.env[model].sudo().with_context(active_test=False).search(
                    [('bxi_aadhaar_hash', '=', hashed)]))
        return holders

    def _bxi_aadhaar_conflict(self, digits):
        """A record of another person already holding `digits`, or None."""
        self.ensure_one()
        for holder in self._bxi_aadhaar_holders(digits):
            if not self._bxi_same_person(holder):
                return holder
        return None

    @api.constrains('aadhar_card', 'user_id')
    def _check_bxi_aadhaar(self):
        for record in self:
            value = record.sudo().aadhar_card
            if not value:
                continue
            digits = normalize_aadhaar(value)
            if not digits:
                raise ValidationError(_(
                    'Enter a valid 12-digit Aadhaar number (it cannot start with 0 or 1, '
                    'and the last digit is a check digit).'))
            if record._bxi_aadhaar_conflict(digits):
                raise AadhaarInUseError(_('This Aadhaar number is already registered to another person.'))

    @api.model
    def _bxi_prepare_aadhaar_vals(self, vals):
        """Clean an `aadhar_card` value in create/write vals. A number set
        by the school office (anything but the family's own submission,
        see _submit_aadhar) counts as verified; clearing it resets the
        status."""
        if 'aadhar_card' not in vals:
            return vals
        vals = dict(vals)
        cleaned = clean_aadhaar(vals['aadhar_card'])
        vals['aadhar_card'] = cleaned or False
        if self.env.context.get('bxi_aadhaar_self_submitted') or 'aadhar_verification_status' in vals:
            return vals
        now = fields.Datetime.now()
        if cleaned:
            vals.update(aadhar_verification_status='verified', aadhar_verified_at=now)
            vals.setdefault('aadhar_submitted_at', now)
        else:
            vals.update(aadhar_verification_status='unverified', aadhar_verified_at=False,
                        aadhar_submitted_at=False)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._bxi_prepare_aadhaar_vals(vals) for vals in vals_list])

    def write(self, vals):
        return super().write(self._bxi_prepare_aadhaar_vals(vals))

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
        """The family's own submission from the app: waits for a reviewer
        (status 'pending'). Raises ValidationError for an invalid number
        and AadhaarInUseError for someone else's."""
        self.ensure_one()
        if not aadhar_number:
            raise UserError(_('An Aadhaar number is required.'))
        self.with_context(bxi_aadhaar_self_submitted=True).write({
            'aadhar_card': aadhar_number,
            'aadhar_verification_status': 'pending',
            'aadhar_submitted_at': fields.Datetime.now(),
            'aadhar_verified_at': False,
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
