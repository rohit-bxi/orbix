# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, rate_limit
from odoo.addons.bxi_api.controllers.main import BxiApiAuthController

from ..lib.engine import FaceError
from ..models.face_challenge import CHALLENGE_TTL_SECONDS, SELECTION_TTL_SECONDS
from ..models.face_service import FaceEngineUnavailable
from .common import account_summary, face_error, identity, is_face_manager, read_frames, read_payload

NOT_RECOGNISED = 'Face not recognised. Use your password or OTP.'
AMBIGUOUS = "Your face is too close to someone else's to be sure. Use your password or OTP."


def _issue(user, kiosk, device_name):
    """Same response as /auth/login plus the `identity` block, for a
    session that must confirm the password/OTP before sensitive actions
    (step_up_required)."""
    if kiosk:
        response = BxiApiAuthController._issue_login_response(
            user, device_name or kiosk.name, auth_method='face_kiosk',
            step_up_required=True, ttl_minutes=kiosk.session_minutes or 15)
        Token = request.env['bxi.api.token'].sudo()
        Token.search([('token_hash', '=', Token._hash(response['token']))]).face_kiosk_id = kiosk
    else:
        response = BxiApiAuthController._issue_login_response(
            user, device_name, auth_method='face',
            step_up_required=True, ttl_days=user.company_id.bxi_face_token_days or 30)
    response['identity'] = identity(user, kiosk._allowed_roles() if kiosk else None)
    return response


def _read_challenge_frames(payload, files):
    """(challenge, {action: photo bytes}, error) - the challenge is used up
    by this call whatever happens next."""
    challenge = request.env['bxi.face.challenge'].sudo()._consume(payload.get('challenge_id'))
    if not challenge:
        return None, None, api_error('This challenge has expired or was already used. Start again.',
                                     status=400, code='challenge_expired')
    actions = challenge._get_actions()
    frames, error = read_frames(payload, files, len(actions), len(actions))
    if error:
        return None, None, error
    by_action = {action: content for action, content in frames if action}
    if set(by_action) != set(actions):
        return None, None, api_error('Send one photo for each action: %s.' % ', '.join(actions),
                                     status=400, code='invalid_frames')
    return challenge, by_action, None


class _Recognition:
    """One recognition run - photos, liveness, matching - shared by face
    login and identify. `run()` returns (outcome, users): outcome is
    'match' (one account), 'select' (several accounts of one person),
    'ambiguous' or 'no_match', or None when `error` holds the response to
    send (photo, liveness, engine or lockout problem)."""

    def __init__(self, challenge, by_action, mode, company, candidates=None, kiosk=None, hint=None,
                 device_name=None):
        env = request.env
        self.service = env['bxi.face.service']
        self.users = env['res.users'].sudo()
        self.challenge, self.by_action, self.mode, self.company = challenge, by_action, mode, company
        self.candidates = candidates if candidates is not None else self.users
        self.kiosk = kiosk if kiosk is not None else env['bxi.face.kiosk']
        self.allowed_roles = self.kiosk._allowed_roles() if self.kiosk else None
        self.error = None
        self.attempt = env['bxi.face.login.attempt'].sudo().create({
            'mode': mode,
            'company_id': company.id,
            'kiosk_id': self.kiosk.id or False,
            'ip': request.httprequest.remote_addr,
            'device_name': device_name,
            'login_hint': hint,
            'target_user_ids': [(6, 0, self.candidates.ids)],
        })

    def fail(self, result, message, status, reason=None, count_against=None, **extra):
        self.attempt.write({'result': result, 'reason': reason})
        if count_against:
            self.service._register_failure(count_against)
        self.error = face_error(message, status, result, **extra)
        return None, self.users

    def run(self):
        Service = self.service
        if self.mode == 'phone':
            locked = self.candidates.filtered(Service._is_locked)
            if locked and locked == self.candidates:
                return self.fail('locked', 'Too many failed attempts. Use your password or OTP, or try again later.', 423)
            self.candidates -= locked

        try:
            engine = Service._get_engine()
        except FaceEngineUnavailable:
            return self.fail('face_engine_unavailable',
                             'Face login is temporarily unavailable. Use your password or OTP.', 503)
        analyses = {}
        for action, content in self.by_action.items():
            try:
                analyses[action] = engine.analyze(content)
            except FaceError as exc:
                return self.fail(exc.code, exc.message, 400, action=action)

        ok, reason, live_score = Service._check_liveness(analyses, self.company)
        if live_score is not None:
            self.attempt.live_score = live_score
        if not ok:
            return self.fail('liveness_failed',
                             "We couldn't confirm a live face. Follow the prompts, or use your password or OTP.",
                             401, reason=reason, count_against=self.candidates)

        embedding = analyses['center'].embedding
        if self.mode == 'phone':
            # The remembered account(s) only.
            scores = Service._user_scores(self.candidates, embedding)
            threshold = self.company.bxi_face_match_threshold
        else:
            # Everyone enrolled at the school: stricter threshold, and the
            # best match must be clearly ahead of the next person.
            scores = Service._gallery_scores(self.company, embedding)
            threshold = self.company.bxi_face_kiosk_match_threshold
        ranked = sorted(scores.values(), reverse=True)
        self.attempt.write({
            'best_score': ranked[0] if ranked else 0.0,
            'second_score': ranked[1] if len(ranked) > 1 else 0.0,
        })
        outcome, user_ids = Service._decide(scores, threshold, self.company.bxi_face_kiosk_match_gap)
        if outcome == 'ambiguous':
            return outcome, self.users
        users = self.users.browse(user_ids).filtered(
            lambda user: Service._eligibility(user, self.allowed_roles)[0])
        if outcome == 'no_match' or not users:
            return 'no_match', self.users
        return ('match' if len(users) == 1 else 'select'), users


class BxiFaceLoginController(http.Controller):

    @http.route('/api/v1/auth/face-login/challenge', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('face_challenge', limit=30)
    def challenge(self, **kwargs):
        """Step 1: which head movements to photograph, in order."""
        challenge = request.env['bxi.face.challenge'].sudo()._create_challenge(request.httprequest.remote_addr)
        return api_response({
            'challenge_id': challenge.name,
            'actions': challenge._get_actions(),
            'expires_in': CHALLENGE_TTL_SECONDS,
        })

    @http.route('/api/v1/auth/face-login', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('face_login', limit=10)
    def face_login(self, **kwargs):
        """Step 2: one photo per challenge action. Who is logging in is
        worked out from the face; the answer's `identity.role` says whether
        it is a student, teacher, parent (or staff).

        - No `login_hint`: the whole school is searched (face-only login).
        - `login_hint` (login, phone or registration number the app
          remembered): only that account is compared - faster to accept,
          and failures count towards that account's lockout.
        - X-Kiosk-Key header: a registered kiosk, whole school, kiosk roles.
        """
        env = request.env
        payload, files, error = read_payload()
        if error:
            return error
        challenge, by_action, error = _read_challenge_frames(payload, files)
        if error:
            return error

        Service = env['bxi.face.service']
        device_name = payload.get('device_name') or None
        kiosk_key = request.httprequest.headers.get('X-Kiosk-Key')
        hint = (payload.get('login_hint') or '').strip() or None
        kiosk = env['bxi.face.kiosk']
        candidates = None
        if kiosk_key:
            kiosk = kiosk.sudo()._from_key(kiosk_key)
            if not kiosk:
                return api_error('Unknown or revoked kiosk key.', status=401, code='invalid_kiosk')
            company = kiosk.company_id
            if not (company.bxi_face_enabled and company.bxi_face_kiosk_enabled):
                return api_error('Face login is not enabled on kiosks.', status=403, code='face_login_disabled')
            mode, hint = 'kiosk', None
        elif hint:
            candidates = Service._users_for_hint(hint)
            company = candidates[:1].company_id or env.company
            mode = 'phone'
        else:
            company = env.company
            if not company.bxi_face_auto_identify:
                return api_error('login_hint is required: face-only login is switched off at this school.',
                                 status=400, code='missing_login_hint')
            mode = 'auto'

        recognition = _Recognition(challenge, by_action, mode, company, candidates, kiosk, hint, device_name)
        outcome, users = recognition.run()
        if recognition.error:
            return recognition.error
        if outcome == 'ambiguous':
            recognition.fail('ambiguous', AMBIGUOUS, 409)
            return recognition.error
        if outcome == 'no_match':
            recognition.fail('face_not_recognised', NOT_RECOGNISED, 401, count_against=recognition.candidates)
            return recognition.error
        if outcome == 'select':
            token = challenge._start_selection(users, kiosk, device_name)
            recognition.attempt.result = 'selection_required'
            return api_response({
                'selection_required': True,
                'selection_token': token,
                'expires_in': SELECTION_TTL_SECONDS,
                'accounts': [account_summary(user, recognition.allowed_roles) for user in users],
            })
        recognition.attempt.write({'result': 'success', 'user_id': users.id})
        return api_response(_issue(users, kiosk, device_name))

    @http.route('/api/v1/auth/face-login/select', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('face_select', limit=10)
    def select_account(self, **kwargs):
        """Step 3, only when step 2 answered `selection_required`: pick
        which of the person's accounts to open. No second scan needed."""
        payload, _files, error = read_payload()
        if error:
            return error
        challenge = request.env['bxi.face.challenge'].sudo()._find_selection(payload.get('selection_token'))
        if not challenge:
            return api_error('This choice has expired. Scan your face again.', status=400, code='selection_expired')
        user_id, error = parse_int(payload.get('user_id'), 'user_id')
        if error:
            return error
        user = challenge.selection_user_ids.filtered(lambda candidate: candidate.id == user_id)
        if not user:
            return api_error('Pick one of the accounts offered.', status=400, code='invalid_account')
        kiosk = challenge.selection_kiosk_id
        Service = request.env['bxi.face.service']
        if not Service._eligibility(user, kiosk._allowed_roles() if kiosk else None)[0]:
            return api_error(NOT_RECOGNISED, status=401, code='face_not_recognised')
        challenge._mark_selection_used()
        request.env['bxi.face.login.attempt'].sudo().create({
            'mode': 'kiosk' if kiosk else 'phone',
            'company_id': user.company_id.id,
            'kiosk_id': kiosk.id or False,
            'ip': request.httprequest.remote_addr,
            'device_name': challenge.selection_device_name,
            'user_id': user.id,
            'result': 'success',
            'reason': 'account chosen',
        })
        return api_response(_issue(user, kiosk, challenge.selection_device_name))

    @http.route('/api/v1/face/identify', type='http', auth='public', methods=['POST'], csrf=False)
    @rate_limit('face_identify', limit=30)
    def identify(self, **kwargs):
        """Who is this, and are they a student, teacher or parent? Same
        challenge and photos as face login, but nothing is logged in - for
        a gate, front desk or kiosk screen. Callers: a registered kiosk
        (X-Kiosk-Key, its roles apply) or a Face Login Manager's bearer
        token. Not open to everyone: it would otherwise be a lookup service
        for anyone's photo."""
        env = request.env
        kiosk = env['bxi.face.kiosk']
        kiosk_key = request.httprequest.headers.get('X-Kiosk-Key')
        if kiosk_key:
            kiosk = kiosk.sudo()._from_key(kiosk_key)
            if not kiosk:
                return api_error('Unknown or revoked kiosk key.', status=401, code='invalid_kiosk')
            company = kiosk.company_id
        else:
            header = request.httprequest.headers.get('Authorization', '')
            token = env['bxi.api.token'].sudo()._verify_token_record(header[7:] if header.startswith('Bearer ') else None)
            if not token:
                return api_error('Invalid or expired token.', status=401, code='unauthorized')
            request.update_env(user=token.user_id.id)
            env = request.env
            if not is_face_manager(env.user):
                return api_error('Only Face Login Managers and kiosks can identify faces.', status=403, code='forbidden')
            company = env.user.company_id
        if not company.bxi_face_enabled:
            return api_error('Face login is not enabled at this school.', status=403, code='face_login_disabled')

        payload, files, error = read_payload()
        if error:
            return error
        challenge, by_action, error = _read_challenge_frames(payload, files)
        if error:
            return error
        recognition = _Recognition(challenge, by_action, 'identify', company, kiosk=kiosk,
                                   device_name=payload.get('device_name') or None)
        outcome, users = recognition.run()
        if recognition.error:
            return recognition.error
        if outcome in ('ambiguous', 'no_match'):
            recognition.attempt.write({
                'result': 'ambiguous' if outcome == 'ambiguous' else 'face_not_recognised'})
            return api_response({
                'identified': False,
                'reason': 'ambiguous' if outcome == 'ambiguous' else 'face_not_recognised',
                'identity': None,
                'accounts': [],
            })
        recognition.attempt.write({'result': 'identified', 'user_id': users[0].id,
                                   'reason': '%s accounts' % len(users) if len(users) > 1 else False})
        accounts = [identity(user, recognition.allowed_roles) for user in users]
        return api_response({
            'identified': True,
            'reason': None,
            'identity': accounts[0],
            'accounts': accounts,
        })
