# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

import base64
import hashlib
import logging
import os
import secrets
from datetime import timedelta

import numpy as np
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from odoo import api, fields, models, tools
from odoo.tools import config

from ..lib import engine as engine_lib
from ..lib.matching import SAME_PERSON_MIN, check_liveness, decide

_logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ml_models')
FALLBACK_KEY_PARAM = 'bxi_face_auth.fallback_key'
# Attempt results that count towards the per-account lockout. Photo
# problems (no face, blur) don't: they are camera trouble, not guessing.
LOCKOUT_RESULTS = ('face_not_recognised', 'liveness_failed')
# Also the order in which a person's main role is picked (see controllers.common.identity).
FACE_ROLES = ('student', 'teacher', 'parent', 'staff')
MAX_HINT_USERS = 5


class FaceEngineUnavailable(Exception):
    """OpenCV or the model files are missing on this server."""


class BxiFaceService(models.AbstractModel):
    """Everything the face controllers share: the recognition engine,
    encryption of stored face data, who may use face login, the matching
    gallery and the lockout counter. Kept on one model so tests can swap
    the engine with a single patch of `_get_engine`."""
    _name = 'bxi.face.service'
    _description = 'Face Login Service'

    # -- engine ----------------------------------------------------------------

    @api.model
    def _get_engine(self):
        try:
            return engine_lib.get_engine(
                config.get('bxi_face_model_dir') or MODEL_DIR,
                config.get('bxi_face_antispoof_model') or None)
        except Exception as exc:
            _logger.error('Face login engine could not be loaded: %s', exc)
            raise FaceEngineUnavailable() from exc

    @api.model
    def _engine_status(self):
        try:
            engine = self._get_engine()
        except FaceEngineUnavailable:
            return {'available': False, 'model_version': None, 'antispoof_model': False}
        return {
            'available': True,
            'model_version': engine.model_version,
            'antispoof_model': bool(getattr(engine, 'has_antispoof', False)),
        }

    # -- encryption --------------------------------------------------------------

    @api.model
    def _fernet(self):
        """Face embeddings and photos are encrypted with `bxi_face_key` from
        odoo.conf, so a database dump alone doesn't carry usable biometric
        data. `bxi_face_key_previous` keeps old data readable during a key
        change. Without a configured key a random one is stored in the
        database (and a warning logged): it still works, but then the dump
        holds the key too."""
        keys = [config.get('bxi_face_key'), config.get('bxi_face_key_previous')]
        params = self.env['ir.config_parameter'].sudo()
        fallback = params.get_param(FALLBACK_KEY_PARAM)
        if not keys[0] and not fallback:
            fallback = secrets.token_urlsafe(48)
            params.set_param(FALLBACK_KEY_PARAM, fallback)
            _logger.warning(
                'Face login: no bxi_face_key in the Odoo config file; face data is encrypted with '
                'a key stored in the database instead. Set bxi_face_key to keep the key out of backups.')
        keys.append(fallback)
        return MultiFernet([
            Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))
            for key in keys if key
        ])

    @api.model
    def _key_source(self):
        return 'config' if config.get('bxi_face_key') else 'database'

    @api.model
    def _encrypt(self, raw_bytes):
        return self._fernet().encrypt(raw_bytes)

    @api.model
    def _decrypt(self, token):
        """Raw bytes, or None if the data can't be decrypted (wrong key)."""
        if not token:
            return None
        if isinstance(token, str):
            token = token.encode()
        try:
            return self._fernet().decrypt(token)
        except InvalidToken:
            _logger.error('Face login: stored face data could not be decrypted (has bxi_face_key changed?)')
            return None

    # -- people ------------------------------------------------------------------

    @api.model
    def _school_records(self, user):
        context = user._bxi_school_context()
        return context['student'], context['faculty'], context['parent']

    @api.model
    def _face_roles(self, user):
        """The face-login roles (student/teacher/parent/staff) this account
        holds, regardless of settings."""
        roles = set(user._bxi_roles())
        result = [role for role in ('student', 'teacher', 'parent') if role in roles]
        if 'staff' in roles and 'teacher' not in roles:
            result.append('staff')
        return result

    @api.model
    def _active_consent(self, student):
        return self.env['bxi.face.consent'].sudo().search([
            ('student_id', '=', student.id), ('withdrawn_at', '=', False),
        ], limit=1)

    @api.model
    def _eligible_roles(self, user, allowed_roles=None):
        """(roles, reason): the face-login roles `user` may use right now -
        settings, consent and class filter applied, in ROLE_ORDER - and,
        when there are none, why. Ignores whether a face is enrolled.
        `allowed_roles` further limits the roles (kiosk settings)."""
        user = user.sudo()
        company = user.company_id
        if not user.active:
            return [], 'inactive'
        if not company.bxi_face_enabled:
            return [], 'disabled'
        if user.has_group('base.group_system') and not company.bxi_face_allow_staff:
            return [], 'role_not_allowed'
        roles = self._face_roles(user)
        if allowed_roles is not None:
            roles = [role for role in roles if role in allowed_roles]
        student = self._school_records(user)[0]
        eligible, reason = [], 'role_not_allowed'
        for role in roles:
            if role == 'student':
                if not company.bxi_face_allow_student:
                    continue
                if company.bxi_face_student_consent_required and not self._active_consent(student):
                    reason = 'consent_required'
                    continue
                if company.bxi_face_student_course_ids:
                    running = student.course_detail_ids.filtered(lambda line: line.state == 'running')
                    if not running.course_id & company.bxi_face_student_course_ids:
                        continue
                eligible.append(role)
            elif company['bxi_face_allow_%s' % role]:
                eligible.append(role)
        return eligible, (None if eligible else reason)

    @api.model
    def _eligibility(self, user, allowed_roles=None):
        """(ok, reason) - see _eligible_roles."""
        roles, reason = self._eligible_roles(user, allowed_roles)
        return bool(roles), reason

    @api.model
    def _users_for_hint(self, hint):
        """Accounts a `login_hint` can mean: the login itself, a phone
        number on the account (or op.parent mobile), or a student's
        registration number. Several results are possible (a shared family
        phone); the face decides between them."""
        hint = (hint or '').strip()
        Users = self.env['res.users'].sudo()
        if not hint:
            return Users
        users = Users.search([('login', 'in', list({hint, hint.lower()}))])
        digits = sum(ch.isdigit() for ch in hint)
        if digits >= 6 and all(ch.isdigit() or ch in ' +-()' for ch in hint):
            users |= Users._bxi_find_users_by_phone(hint)
        students = self.env['op.student'].sudo().search([('gr_no', '=', hint)], limit=2)
        users |= students.user_id
        return users.filtered('active')[:MAX_HINT_USERS]

    # -- matching ------------------------------------------------------------------

    @api.model
    def _active_templates(self, domain):
        return self.env['bxi.face.template'].sudo().search(
            domain + [('enrolment_id.state', '=', 'active')])

    @tools.ormcache('company_id')
    def _gallery(self, company_id):
        """(user_ids, matrix) of every active face in the school, decrypted
        once per worker and kept until an enrolment changes state
        (see bxi.face.enrolment._invalidate_gallery)."""
        templates = self._active_templates([('company_id', '=', company_id), ('user_id.active', '=', True)])
        user_ids, rows = [], []
        for template in templates:
            embedding = template._get_embedding()
            if embedding is not None:
                user_ids.append(template.user_id.id)
                rows.append(embedding)
        matrix = np.vstack(rows) if rows else np.zeros((0, engine_lib.EMBEDDING_SIZE), dtype=np.float32)
        matrix.flags.writeable = False
        return tuple(user_ids), matrix

    @api.model
    def _gallery_scores(self, company, embedding, exclude_user_ids=()):
        user_ids, matrix = self._gallery(company.id)
        scores = {}
        if not user_ids:
            return scores
        similarities = matrix @ embedding
        for uid, score in zip(user_ids, similarities.tolist()):
            if uid in exclude_user_ids:
                continue
            if score > scores.get(uid, -1.0):
                scores[uid] = score
        return scores

    @api.model
    def _user_scores(self, users, embedding):
        scores = {}
        for template in self._active_templates([('user_id', 'in', users.ids)]):
            stored = template._get_embedding()
            if stored is None:
                continue
            score = float(np.dot(stored, embedding))
            if score > scores.get(template.user_id.id, -1.0):
                scores[template.user_id.id] = score
        return scores

    @api.model
    def _same_person_map(self, user_ids):
        """user id -> ids of other accounts staff confirmed are the same
        person (both directions)."""
        mapping = {}
        enrolments = self.env['bxi.face.enrolment'].sudo().search([
            ('state', '=', 'active'), '|', ('user_id', 'in', list(user_ids)),
            ('same_person_user_ids', 'in', list(user_ids)),
        ])
        for enrolment in enrolments:
            for other in enrolment.same_person_user_ids:
                mapping.setdefault(enrolment.user_id.id, set()).add(other.id)
                mapping.setdefault(other.id, set()).add(enrolment.user_id.id)
        return mapping

    @api.model
    def _decide(self, user_scores, threshold, gap):
        return decide(user_scores, threshold, gap, self._same_person_map(user_scores))

    @api.model
    def _check_liveness(self, analyses, company):
        """(ok, reason, min_live_score) for a {action: FaceAnalysis} dict."""
        center = analyses['center']
        consistency = {
            action: float(np.dot(analysis.embedding, center.embedding))
            for action, analysis in analyses.items() if action != 'center'
        }
        if not company.bxi_face_liveness_required:
            # Still refuse a different person in the turned frames.
            if any(score < SAME_PERSON_MIN for score in consistency.values()):
                return False, 'face_changed', None
            return True, None, None
        return check_liveness(
            {action: analysis.yaw for action, analysis in analyses.items()},
            consistency,
            [analysis.live_score for analysis in analyses.values()],
            company.bxi_face_antispoof_threshold,
        )

    # -- lockout -------------------------------------------------------------------

    @api.model
    def _recent_failures(self, user):
        company = user.company_id
        since = fields.Datetime.now() - timedelta(minutes=company.bxi_face_lockout_minutes or 15)
        Attempt = self.env['bxi.face.login.attempt'].sudo()
        last_success = Attempt.search([
            ('user_id', '=', user.id), ('result', '=', 'success'), ('create_date', '>=', since),
        ], order='create_date desc, id desc', limit=1)
        domain = [
            ('target_user_ids', 'in', user.id), ('result', 'in', LOCKOUT_RESULTS), ('create_date', '>=', since),
        ]
        if last_success:
            domain.append(('id', '>', last_success.id))
        return Attempt.search_count(domain)

    @api.model
    def _is_locked(self, user):
        limit = user.company_id.bxi_face_max_failures or 5
        return self._recent_failures(user) >= limit

    @api.model
    def _register_failure(self, users):
        """Called after a failed attempt was logged against `users`; warns
        each account the moment it becomes locked."""
        for user in users:
            company = user.company_id
            if self._recent_failures(user) == (company.bxi_face_max_failures or 5):
                self.env['bxi.notification'].sudo()._notify(
                    user,
                    'Face login paused',
                    'Several face login attempts on your account did not match, so face login is '
                    'paused for %s minutes. Password and OTP login still work. If this was not you, '
                    'change your password.' % (company.bxi_face_lockout_minutes or 15),
                    category='security',
                )
