# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import api, fields, models


class BxiFaceConsent(models.Model):
    """A parent's consent to face login for a student (India's DPDP Act
    needs verifiable parental consent before processing a child's
    biometric data). Withdrawing it revokes the student's enrolments and
    deletes their face data."""
    _name = 'bxi.face.consent'
    _description = 'Face Login Parental Consent'
    _order = 'granted_at desc, id desc'

    student_id = fields.Many2one('op.student', required=True, index=True, ondelete='cascade')
    granted_by_id = fields.Many2one('res.users', string='Given By', required=True)
    method = fields.Selection([
        ('app', 'Parent app'),
        ('offline', 'Signed form, recorded by staff'),
    ], required=True, default='app')
    reference = fields.Char(help='For offline consent: the form or register reference.')
    consent_version = fields.Char()
    granted_at = fields.Datetime(required=True, default=fields.Datetime.now)
    withdrawn_at = fields.Datetime(index=True)
    withdrawn_by_id = fields.Many2one('res.users', string='Withdrawn By')

    @api.model
    def _grant(self, student, granted_by, method='app', reference=None):
        existing = self.env['bxi.face.service']._active_consent(student)
        if existing:
            return existing
        return self.sudo().create({
            'student_id': student.id,
            'granted_by_id': granted_by.id,
            'method': method,
            'reference': reference or False,
            'consent_version': (student.user_id.company_id or self.env.company).bxi_face_consent_version,
        })

    def _withdraw(self, withdrawn_by):
        self.sudo().write({'withdrawn_at': fields.Datetime.now(), 'withdrawn_by_id': withdrawn_by.id})
        users = self.student_id.user_id
        if users:
            self.env['bxi.face.enrolment'].sudo().search([
                ('user_id', 'in', users.ids), ('state', 'in', ('active', 'pending')),
            ])._end('revoked', 'parental consent withdrawn')
