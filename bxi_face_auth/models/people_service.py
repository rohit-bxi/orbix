# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import _, api, models

from odoo.addons.bxi_api_support.models.people_service import PeopleError


class BxiPeopleService(models.AbstractModel):
    """Face recognition for the office's teacher/student/parent screens:
    the same in-person enrolment as POST /api/v1/admin/face/enrol, run as
    part of creating or updating the person."""
    _inherit = 'bxi.people.service'

    @api.model
    def _face_available(self):
        return True

    @api.model
    def _apply_face(self, record, user, face):
        # Imported here: controllers.common imports this package's models.
        from ..controllers.common import ENROL_MAX_FRAMES, MAX_FRAME_BYTES, _decode_image, analyze_enrolment_frames

        Enrolment = self.env['bxi.face.enrolment'].sudo()
        current = Enrolment.search([('user_id', '=', user.id), ('state', 'in', ('active', 'pending'))])
        if not face.get('enabled'):
            current._end('revoked', 'face recognition turned off by the school office')
            return
        images = face.get('images') or ([face['image']] if face.get('image') else [])
        if not images:
            if current:
                return
            raise PeopleError(_('face.image is required to turn face recognition on.'), 'missing_face_image')
        if not isinstance(images, list) or len(images) > ENROL_MAX_FRAMES:
            raise PeopleError(_('Send between 1 and %s photos.', ENROL_MAX_FRAMES), 'invalid_frames')
        frames = []
        for index, image in enumerate(images):
            data = _decode_image(image.get('image') if isinstance(image, dict) else image)
            if not data:
                raise PeopleError(_('Photo %s is not valid base64 image data.', index + 1), 'invalid_image')
            if len(data) > MAX_FRAME_BYTES:
                raise PeopleError(_('Each photo must be 5 MB or smaller.'), 'file_too_large', status=413)
            frames.append((None, data))
        analyses, actions, error = analyze_enrolment_frames(frames)
        if error:
            raise PeopleError(None, None, response=error)

        Service = self.env['bxi.face.service']
        student = Service._school_records(user)[0]
        consent_by = user
        if student:
            consent = Service._active_consent(student)
            reference = (face.get('consent_reference') or '').strip()
            if not consent and reference:
                consent = self.env['bxi.face.consent'].sudo()._grant(
                    student, self.env.user, method='offline', reference=reference)
            if not consent and user.company_id.bxi_face_student_consent_required:
                raise PeopleError(_("Record the parent's consent first (face.consent_reference: the signed "
                                    "form number)."), 'consent_required')
            consent_by = consent.granted_by_id if consent else None
        enrolment = Enrolment._create_from_analyses(
            user, analyses, 'staff', self.env.user, consent_by=consent_by, actions=actions)
        if not enrolment.duplicate_user_ids:
            enrolment._activate(self.env.user)

    @api.model
    def _face_status(self, user):
        from ..controllers.common import face_status
        return face_status(user)
