# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from datetime import timedelta

import numpy as np

from odoo import api, fields, models

ENROLMENT_STATES = [
    ('pending', 'Pending Review'),
    ('active', 'Active'),
    ('rejected', 'Rejected'),
    ('revoked', 'Revoked'),
    ('expired', 'Expired'),
]
# Pending enrolments nobody reviewed are dropped (with their photos) after this.
PENDING_MAX_DAYS = 30


class BxiFaceEnrolment(models.Model):
    """One registration of a person's face for face login: 1-5 photos
    (bxi.face.template) plus who submitted it, who consented and who
    approved it. Only 'active' enrolments are matched against. Leaving the
    active/pending states deletes the photos and embeddings - the record
    itself stays as an audit trail without any biometric data."""
    _name = 'bxi.face.enrolment'
    _description = 'Face Login Enrolment'
    _order = 'create_date desc, id desc'

    user_id = fields.Many2one('res.users', string='Account', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one('res.company', required=True, index=True)
    student_id = fields.Many2one('op.student', index=True, ondelete='set null')
    faculty_id = fields.Many2one('op.faculty', string='Teacher', index=True, ondelete='set null')
    parent_id = fields.Many2one('op.parent', index=True, ondelete='set null')
    state = fields.Selection(ENROLMENT_STATES, default='pending', required=True, index=True)
    source = fields.Selection([
        ('self', 'Self (app)'),
        ('parent', 'Parent (app)'),
        ('staff', 'Staff (in person)'),
    ], required=True)
    submitted_by_id = fields.Many2one('res.users', string='Submitted By')
    consent_by_id = fields.Many2one('res.users', string='Consent Given By')
    consent_at = fields.Datetime()
    consent_version = fields.Char()
    reviewed_by_id = fields.Many2one('res.users', string='Reviewed By')
    reviewed_at = fields.Datetime()
    reject_reason = fields.Text()
    activated_at = fields.Datetime()
    expires_at = fields.Datetime(index=True)
    ended_at = fields.Datetime(string='Revoked/Expired At')
    end_reason = fields.Char()
    model_version = fields.Char()
    duplicate_user_ids = fields.Many2many(
        'res.users', 'bxi_face_enrolment_duplicate_rel', 'enrolment_id', 'user_id',
        string='Possible Duplicates', help='Other enrolled accounts this face matched when it was submitted.')
    same_person_user_ids = fields.Many2many(
        'res.users', 'bxi_face_enrolment_same_person_rel', 'enrolment_id', 'user_id',
        string='Same Person As', help='Other accounts staff confirmed belong to the same person; '
                                      'face login then offers a choice of account.')
    template_ids = fields.One2many('bxi.face.template', 'enrolment_id', string='Photos')
    template_count = fields.Integer(compute='_compute_template_count')

    @api.depends('template_ids')
    def _compute_template_count(self):
        for enrolment in self:
            enrolment.template_count = len(enrolment.template_ids)

    # -- creation ----------------------------------------------------------------

    @api.model
    def _create_from_analyses(self, user, analyses, source, submitted_by, consent_by=None, actions=None):
        """Create a pending enrolment for `user` from engine analyses
        (one per photo). Replaces any earlier pending enrolment, and flags
        other enrolled accounts the face matches."""
        Service = self.env['bxi.face.service']
        user = user.sudo()
        student, faculty, parent = Service._school_records(user)
        company = user.company_id
        self.sudo().search([('user_id', '=', user.id), ('state', '=', 'pending')])._end(
            'revoked', 'replaced by a new submission')

        frontal = min(analyses, key=lambda analysis: abs(analysis.yaw))
        scores = Service._gallery_scores(company, frontal.embedding, exclude_user_ids=(user.id,))
        duplicates = [uid for uid, score in scores.items() if score >= company.bxi_face_match_threshold]

        engine_version = getattr(Service._get_engine(), 'model_version', False)
        enrolment = self.sudo().create({
            'user_id': user.id,
            'company_id': company.id,
            'student_id': student.id or False,
            'faculty_id': faculty.id or False,
            'parent_id': parent.id or False,
            'source': source,
            'submitted_by_id': submitted_by.id,
            'consent_by_id': consent_by.id if consent_by else False,
            'consent_at': fields.Datetime.now() if consent_by else False,
            'consent_version': company.bxi_face_consent_version if consent_by else False,
            'model_version': engine_version,
            'duplicate_user_ids': [(6, 0, duplicates)],
        })
        Template = self.env['bxi.face.template'].sudo()
        for sequence, analysis in enumerate(analyses):
            Template._create_from_analysis(
                enrolment, analysis, sequence, (actions or [None] * len(analyses))[sequence])
        return enrolment

    # -- transitions -----------------------------------------------------------------

    def _invalidate_gallery(self):
        self.env.registry.clear_cache()

    def _activate(self, reviewer, same_person_users=None):
        """Make this enrolment the one used for login; any earlier active
        enrolment of the same account is superseded."""
        now = fields.Datetime.now()
        for enrolment in self.sudo():
            company = enrolment.company_id
            earlier = self.sudo().search([
                ('user_id', '=', enrolment.user_id.id), ('state', '=', 'active'), ('id', '!=', enrolment.id),
            ])
            earlier._end('revoked', 'replaced by a newer enrolment')
            validity = company.bxi_face_student_validity_days
            enrolment.write({
                'state': 'active',
                'activated_at': now,
                'reviewed_by_id': reviewer.id,
                'reviewed_at': now,
                'expires_at': now + timedelta(days=validity) if enrolment.student_id and validity else False,
                'same_person_user_ids': [(6, 0, (same_person_users or self.env['res.users']).ids)],
            })
            # The identity photo check (bxi_identity_verification) asks
            # staff the same question; don't make them answer it twice.
            for record in (enrolment.student_id, enrolment.parent_id, enrolment.faculty_id):
                if record and 'face_verification_status' in record._fields \
                        and record.face_verification_status != 'verified':
                    record.write({'face_verification_status': 'verified', 'face_verified_at': now})
        self._invalidate_gallery()

    def _reject(self, reviewer, reason):
        now = fields.Datetime.now()
        self.sudo().write({
            'state': 'rejected', 'reviewed_by_id': reviewer.id, 'reviewed_at': now,
            'reject_reason': reason or False, 'ended_at': now,
        })
        self.sudo().template_ids.unlink()
        self._invalidate_gallery()

    def _end(self, state, reason):
        """Revoke or expire: the photos and embeddings are deleted."""
        if not self:
            return
        self.sudo().write({'state': state, 'ended_at': fields.Datetime.now(), 'end_reason': reason})
        self.sudo().template_ids.unlink()
        self._invalidate_gallery()

    # -- helpers -----------------------------------------------------------------------

    def _frontal_embedding(self):
        self.ensure_one()
        templates = self.template_ids.sorted(lambda template: abs(template.yaw))
        for template in templates:
            embedding = template._get_embedding()
            if embedding is not None:
                return embedding
        return None

    def _recheck_duplicates(self):
        """Duplicates against the faces active right now (others may have
        been approved since this one was submitted)."""
        self.ensure_one()
        embedding = self._frontal_embedding()
        if embedding is None:
            return self.env['res.users']
        scores = self.env['bxi.face.service']._gallery_scores(
            self.company_id, np.asarray(embedding), exclude_user_ids=(self.user_id.id,))
        threshold = self.company_id.bxi_face_match_threshold
        return self.env['res.users'].browse([uid for uid, score in scores.items() if score >= threshold])

    # -- cron ----------------------------------------------------------------------------

    @api.model
    def _cron_maintenance(self):
        """Daily: expire old student enrolments, drop enrolments of
        archived accounts and stale pending ones, and purge old challenges
        and login attempts."""
        now = fields.Datetime.now()
        Enrolment = self.sudo()
        Enrolment.search([('state', '=', 'active'), ('expires_at', '!=', False), ('expires_at', '<', now)])._end(
            'expired', 'validity period ended')
        Enrolment.search([('state', 'in', ('active', 'pending')), ('user_id.active', '=', False)])._end(
            'revoked', 'account archived')
        Enrolment.search([('state', 'in', ('active', 'pending')), ('student_id.active', '=', False),
                          ('student_id', '!=', False)])._end('revoked', 'student record archived')
        Enrolment.search([('state', '=', 'pending'), ('create_date', '<', now - timedelta(days=PENDING_MAX_DAYS))])._end(
            'expired', 'not reviewed in time')
        self.env['bxi.face.challenge'].sudo().search([('create_date', '<', now - timedelta(days=1))]).unlink()
        Attempt = self.env['bxi.face.login.attempt'].sudo()
        for company in self.env['res.company'].sudo().search([]):
            days = company.bxi_face_attempt_retention_days
            if days:
                Attempt.search([('company_id', '=', company.id),
                                ('create_date', '<', now - timedelta(days=days))]).unlink()
