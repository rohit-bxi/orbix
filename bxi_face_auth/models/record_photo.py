# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Face login from the photo on the school record.

The photo on a student, teacher or parent (`image_1920` of their contact,
set by the form's CLICK IMAGE button, an upload, the office's people API or
the person's own profile-photo upload) is used as their face for face
login: whenever it changes, the face is rebuilt from it and stored as an
active enrolment with source 'record'. Matching, liveness and lockout are
the same as for any other enrolment. The company setting
`bxi_face_use_record_photo` switches this on or off.
"""
import base64
import hashlib
import logging

from odoo import api, fields, models
from odoo.tools.mimetypes import guess_mimetype

from ..lib.engine import FaceError
from .face_service import FaceEngineUnavailable

_logger = logging.getLogger(__name__)

RECORD_SOURCE = 'record'
OPEN_STATES = ('active', 'pending')


class ResCompany(models.Model):
    _inherit = 'res.company'

    bxi_face_use_record_photo = fields.Boolean(
        string='Face Login from Record Photo', default=True,
        help='Use the photo on the student, teacher or parent record as their face for face login. '
             'The face is rebuilt whenever that photo changes.')


class BxiFaceEnrolment(models.Model):
    _inherit = 'bxi.face.enrolment'

    source = fields.Selection(selection_add=[(RECORD_SOURCE, 'School Record Photo')],
                              ondelete={RECORD_SOURCE: 'cascade'})

    def _cron_maintenance(self):
        super()._cron_maintenance()
        # Catch photos changed while the engine was down, or before face
        # login was switched on.
        self.env['bxi.face.service']._sync_all_record_photos()


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def write(self, vals):
        res = super().write(vals)
        if 'image_1920' in vals:
            self.env['bxi.face.service']._users_of_photo_partners(self)._bxi_sync_record_photo()
        return res


class ResUsers(models.Model):
    _inherit = 'res.users'

    bxi_face_photo_checksum = fields.Char(copy=False, readonly=True, groups='base.group_system',
                                          help='SHA-256 of the record photo the face was last built from.')
    bxi_face_photo_error = fields.Char(string='Record Photo Problem', copy=False, readonly=True,
                                       groups='base.group_system',
                                       help='Why no face could be built from the record photo (e.g. no_face).')

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        # A login created for someone who already has a photo.
        users._bxi_sync_record_photo()
        return users

    def _bxi_sync_record_photo(self, force=False):
        """Rebuild each user's face from their record photo. Never raises:
        a problem is logged and must not undo the photo or login change."""
        Service = self.env['bxi.face.service']
        results = {}
        for user in self.sudo():
            try:
                with self.env.cr.savepoint():
                    results[user.id] = Service._sync_record_photo(user, force=force)
            except Exception:  # noqa: BLE001
                _logger.exception('Face login: could not build the face of user %s from the record photo.', user.id)
                results[user.id] = 'error'
        return results


class _LinkedLoginSync(models.AbstractModel):
    """A login is created first and linked to its student/teacher/parent
    record right after, so the face is built when that link is set."""
    _name = 'bxi.face.record.photo.link'
    _description = 'Face Login: sync on login link'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered('user_id').user_id._bxi_sync_record_photo()
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get('user_id'):
            self.user_id._bxi_sync_record_photo()
        return res


class OpStudent(models.Model):
    _name = 'op.student'
    _inherit = ['op.student', 'bxi.face.record.photo.link']


class OpFaculty(models.Model):
    _name = 'op.faculty'
    _inherit = ['op.faculty', 'bxi.face.record.photo.link']


class OpParent(models.Model):
    _name = 'op.parent'
    _inherit = ['op.parent', 'bxi.face.record.photo.link']


class BxiFaceService(models.AbstractModel):
    _inherit = 'bxi.face.service'

    @api.model
    def _record_photo_enabled(self, company):
        return bool(company.bxi_face_enabled and company.bxi_face_use_record_photo)

    @api.model
    def _sync_record_photo(self, user, force=False):
        """Build `user`'s face from the photo on their contact. Returns what
        happened: 'active', 'pending' (looks like another account; a Face
        Login Manager decides), 'removed', 'unchanged', 'skipped' or the
        photo problem ('no_face', 'multiple_faces', 'poor_quality',
        'invalid_image', 'engine_unavailable')."""
        user = user.sudo()
        if not user.active or not self._record_photo_enabled(user.company_id) \
                or not any(self._school_records(user)):
            return 'skipped'
        content = self._record_photo_content(user)
        checksum = hashlib.sha256(content).hexdigest() if content else False
        if not force and checksum == (user.bxi_face_photo_checksum or False):
            return 'unchanged'
        Enrolment = self.env['bxi.face.enrolment'].sudo()
        current = Enrolment.search([
            ('user_id', '=', user.id), ('source', '=', RECORD_SOURCE), ('state', 'in', OPEN_STATES)])
        if not content:
            current._end('revoked', 'record photo removed')
            user.write({'bxi_face_photo_checksum': False, 'bxi_face_photo_error': False})
            return 'removed'
        try:
            engine = self._get_engine()
        except FaceEngineUnavailable:
            # The checksum is not stored, so the daily job tries again.
            return 'engine_unavailable'
        try:
            analysis = engine.analyze(content)
        except FaceError as exc:
            current._end('revoked', 'record photo changed: %s' % exc.code)
            user.write({'bxi_face_photo_checksum': checksum, 'bxi_face_photo_error': exc.code})
            _logger.info('Face login: record photo of user %s has no usable face (%s).', user.id, exc.code)
            return exc.code
        student = self._school_records(user)[0]
        if student:
            consent = self._active_consent(student)
            consent_by = consent.granted_by_id if consent else None
        else:
            consent_by = user
        reviewer = self.env.user
        enrolment = Enrolment._create_from_analyses(
            user, [analysis], RECORD_SOURCE, reviewer, consent_by=consent_by, actions=['center'])
        if not enrolment.duplicate_user_ids:
            # Replaces any earlier active face of this account.
            enrolment._activate(reviewer)
        else:
            current._end('revoked', 'replaced by a new record photo')
        user.write({'bxi_face_photo_checksum': checksum, 'bxi_face_photo_error': False})
        return enrolment.state

    @api.model
    def _record_photo_content(self, user):
        """The photo (bytes) on the person's school record - student, then
        teacher, then parent - else on their login's contact. Odoo's
        generated letter avatars (SVG) are not photos and count as none."""
        student, faculty, parent = self._school_records(user)
        partners = [record.partner_id for record in (student, faculty) if record] \
            + ([parent.name] if parent else []) + [user.partner_id]
        for partner in partners:
            value = partner.with_context(bin_size=False).image_1920
            content = base64.b64decode(value) if value else b''
            if content and guess_mimetype(content).startswith('image/') \
                    and guess_mimetype(content) != 'image/svg+xml':
                return content
        return b''

    @api.model
    def _users_of_photo_partners(self, partners):
        """Logins whose face comes from these contacts' photos: their own
        contact, or the contact of their student/teacher/parent record."""
        Users = self.env['res.users'].sudo().with_context(active_test=False)
        users = Users.search([('partner_id', 'in', partners.ids)])
        users |= self.env['op.student'].sudo().search([('partner_id', 'in', partners.ids)]).user_id
        users |= self.env['op.faculty'].sudo().search([('partner_id', 'in', partners.ids)]).user_id
        users |= self.env['op.parent'].sudo().search([('name', 'in', partners.ids)]).user_id
        return users

    @api.model
    def _record_photo_users(self, companies=None):
        """Active logins of students, teachers and parents in companies that
        use record photos."""
        companies = companies if companies is not None else self.env['res.company'].sudo().search([])
        companies = companies.filtered(self._record_photo_enabled)
        if not companies:
            return self.env['res.users']
        users = (self.env['op.student'].sudo().search([('user_id', '!=', False)]).user_id
                 | self.env['op.faculty'].sudo().search([('user_id', '!=', False)]).user_id
                 | self.env['op.parent'].sudo().search([('user_id', '!=', False)]).user_id)
        return users.filtered(lambda user: user.active and user.company_id in companies)

    @api.model
    def _sync_all_record_photos(self, companies=None, force=False):
        """Sync every student, teacher and parent login; returns
        {outcome: count}."""
        summary = {}
        for outcome in self._record_photo_users(companies)._bxi_sync_record_photo(force=force).values():
            summary[outcome] = summary.get(outcome, 0) + 1
        return summary

    @api.model
    def _drop_record_photo_faces(self, company):
        """Turning the setting off: faces built from record photos stop
        working at once."""
        Enrolment = self.env['bxi.face.enrolment'].sudo()
        enrolments = Enrolment.search([
            ('company_id', '=', company.id), ('source', '=', RECORD_SOURCE), ('state', 'in', OPEN_STATES)])
        enrolments._end('revoked', 'record photo face login switched off')
        enrolments.user_id.write({'bxi_face_photo_checksum': False})
        return len(enrolments)
