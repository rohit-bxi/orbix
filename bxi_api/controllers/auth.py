# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

"""Shared API auth decorator and response envelope.

Every Orbix API controller - in this module or any other bxi_* module that
depends on it - should use `api_response`/`api_error` for its return value
and `@require_auth` on any route that needs to know which app user is
calling, instead of building its own auth or response shape.
"""

import base64
import binascii
import re
import time
from collections import defaultdict, deque
from functools import wraps

import psycopg2
import psycopg2.errors

import odoo.modules.module
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import content_disposition, request

# Largest single upload accepted by parse_request() - homework submissions,
# RTE documents and avatars are photos/PDFs, not videos.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def api_response(data=None, status=200, meta=None):
    body = {'success': True, 'data': data if data is not None else {}}
    if meta:
        body['meta'] = meta
    return request.make_json_response(body, status=status)


def api_error(message, status=400, code=None):
    body = {'success': False, 'error': {'message': message, 'code': code or status}}
    return request.make_json_response(body, status=status)


def api_file_response(content, filename, mimetype='application/pdf'):
    """Binary download (PDF report, attachment) - the one response shape
    that is deliberately not the JSON envelope, since the app hands the
    bytes straight to a viewer/share sheet."""
    return request.make_response(content, headers=[
        ('Content-Type', mimetype),
        ('Content-Length', str(len(content))),
        ('Content-Disposition', content_disposition(filename)),
    ])


def parse_request():
    """Return (payload, files, error) for a POST that may carry files.

    Accepts either multipart/form-data (form fields become the payload,
    every uploaded part becomes a file) or a JSON body whose optional
    `attachments` key is a list of {name, data (base64), mimetype}. Each
    file is a dict {name, content (bytes), mimetype}. `error` is an
    api_error(...) for an oversized or undecodable file, else None.
    """
    httprequest = request.httprequest
    files = []
    if httprequest.mimetype == 'multipart/form-data':
        payload = httprequest.form.to_dict()
        for storage in httprequest.files.values():
            content = storage.read()
            files.append({
                'name': storage.filename or 'upload',
                'content': content,
                'mimetype': storage.mimetype or 'application/octet-stream',
            })
    else:
        payload = request.get_json_data() if httprequest.get_data() else {}
        payload = payload or {}
        for entry in payload.pop('attachments', None) or []:
            try:
                content = base64.b64decode(entry.get('data') or '', validate=True)
            except (binascii.Error, ValueError, AttributeError):
                return payload, [], api_error(
                    'Attachment data must be base64-encoded.', status=400, code='invalid_attachment')
            files.append({
                'name': entry.get('name') or 'upload',
                'content': content,
                'mimetype': entry.get('mimetype') or 'application/octet-stream',
            })
    for file in files:
        if len(file['content']) > MAX_UPLOAD_BYTES:
            return payload, [], api_error(
                'Each file must be %s MB or smaller.' % (MAX_UPLOAD_BYTES // (1024 * 1024)),
                status=413, code='file_too_large')
    return payload, files, None


# Per-process sliding-window limiter for the public (unauthenticated)
# routes - same approach sttl_face_attendance's /employee/images uses. Each
# worker process keeps its own window, so this blunts scripted abuse of a
# single worker; put a real limit at the reverse proxy for a hard guarantee.
# Password login is deliberately not wrapped: Odoo's own per-IP
# login cooldown already covers brute force there.
_rate_buckets = defaultdict(deque)
# Every test request comes from 127.0.0.1, so the limiter stays off while a
# test runs unless that test switches it on to exercise it.
RATE_LIMIT_DURING_TESTS = False


def _rate_limit_active():
    return RATE_LIMIT_DURING_TESTS or not odoo.modules.module.current_test


def rate_limit(bucket, limit, window=60):
    """Allow at most `limit` calls per `window` seconds per client IP to
    the wrapped route; extra calls get a 429 envelope without running it."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not _rate_limit_active():
                return func(*args, **kwargs)
            key = (bucket, request.httprequest.remote_addr)
            now = time.monotonic()
            calls = _rate_buckets[key]
            while calls and now - calls[0] > window:
                calls.popleft()
            if len(calls) >= limit:
                return api_error(
                    'Too many requests. Please wait a minute and try again.', status=429, code='rate_limited')
            calls.append(now)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def parse_int(value, field_name):
    """Parse a user-supplied id/limit/offset. Returns (int_value, None) on
    success or (None, api_error(...)) on a non-numeric value, so a bad
    query-string/payload value gets a clean 400 envelope instead of an
    unhandled ValueError bubbling up as a generic 500."""
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, api_error(
            '%s must be a number.' % field_name, status=400, code='invalid_%s' % field_name)


def call_action(record, method_name, write_vals=None, **kwargs):
    """Call an `action_*` transition method on `record`, translating the
    exceptions those methods already raise for an illegal transition or a
    permission problem into the standard API error envelope, instead of
    every controller re-implementing the same try/except.

    Returns (result, None) on success or (None, api_error(...)) on failure -
    callers should `return error` immediately when the second item isn't
    None, the same way `parse_int` is used.

    `write_vals` (e.g. resolution notes the transition checks for) are
    written first; they and anything the method wrote are rolled back when
    the transition is refused, so a failed call leaves the record as it was.
    """
    try:
        with record.env.cr.savepoint():
            if write_vals:
                record.write(write_vals)
            return getattr(record, method_name)(**kwargs), None
    except AccessError as exc:
        # AccessError subclasses UserError in this Odoo version, so this
        # branch must come first - otherwise every AccessError would match
        # `except UserError` below and get reported as 400 instead of 403.
        return None, api_error(str(exc), status=403, code='forbidden')
    except UserError as exc:
        return None, api_error(str(exc), status=400, code='invalid_transition')


def _model_for_table(env, table):
    for name in env.registry:
        model = env[name]
        if not model._abstract and model._table == table:
            return model
    return None


def integrity_error(exc):
    """API error envelope for a constraint the database refused
    (psycopg2.IntegrityError), worded for an app rather than the backend.
    The cursor must already be usable again (savepoint or transaction
    rolled back) - building the message may read the registry tables."""
    env = request.env
    diag = exc.diag
    model = _model_for_table(env, diag.table_name) if diag.table_name else None
    column = diag.column_name

    def label(col):
        field = model._fields.get(col) if model is not None and col else None
        return field.string if field else (col or 'A required value')

    if isinstance(exc, psycopg2.errors.NotNullViolation):
        return api_error('%s is required.' % label(column), status=400,
                         code='missing_%s' % column if column else 'missing_field')
    if isinstance(exc, psycopg2.errors.ForeignKeyViolation):
        detail = diag.message_detail or ''
        match = re.search(r'Key \((\w+)\)=\(([^)]*)\) is not present', detail)
        if match:
            col, value = match.groups()
            return api_error('%s %s does not exist.' % (col, value), status=400, code='invalid_%s' % col)
        return api_error('This record is still used by other records and cannot be deleted. '
                         'Archive it instead.', status=400, code='in_use')
    message = None
    if model is not None:
        try:
            message = model._sql_error_to_message(exc)
        except Exception:  # noqa: BLE001 - fall back to the plain message below
            message = None
    return api_error(message or 'This conflicts with an existing record: %s' % (diag.message_primary or exc),
                     status=400, code='conflict')


def model_error(exc):
    """API error envelope for an Odoo model exception (AccessError,
    MissingError, ValidationError/UserError) or a refused constraint
    (psycopg2.IntegrityError)."""
    if isinstance(exc, psycopg2.IntegrityError):
        return integrity_error(exc)
    if isinstance(exc, AccessError):
        return api_error(str(exc), status=403, code='forbidden')
    if isinstance(exc, MissingError):
        return api_error(str(exc), status=404, code='not_found')
    return api_error(str(exc), status=400, code='validation_error')


# What an account signed in with a one-time password (set by the school
# office) may call before choosing its own password.
PASSWORD_CHANGE_PENDING_PATHS = frozenset({
    '/api/v1/auth/password/change', '/api/v1/auth/me', '/api/v1/auth/logout',
})


def require_auth(func):
    """Validates the `Authorization: Bearer <token>` header against
    bxi.api.token and, on success, runs the wrapped route with
    `request.env` switched to that token's user (so ir.rule/ACLs apply as
    that user, the same as a normal Odoo request). On failure, returns a
    401 envelope without calling the wrapped route at all.

    A model error or refused constraint the route lets escape (a create
    the route did not guard) rolls the request back and comes back as the
    usual JSON error envelope, not Odoo's HTML error page. Serialization
    failures are not caught, so Odoo still retries those.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth_header = request.httprequest.headers.get('Authorization', '')
        raw_token = auth_header[7:] if auth_header.startswith('Bearer ') else None
        token = request.env['bxi.api.token'].sudo()._verify_token_record(raw_token)
        if not token:
            return api_error('Invalid or expired token.', status=401, code='unauthorized')
        if token.user_id.bxi_must_change_password \
                and request.httprequest.path.rstrip('/') not in PASSWORD_CHANGE_PENDING_PATHS:
            return api_error('Change your one-time password to continue.', status=403,
                             code='password_change_required')
        request.update_env(user=token.user_id.id)
        try:
            return func(*args, **kwargs)
        except (UserError, psycopg2.IntegrityError) as exc:
            request.env.cr.rollback()
            return model_error(exc)
    return wrapper


def require_step_up(func):
    """Use below @require_auth on sensitive routes. A session opened by a
    weaker login method (face login: token.step_up_required) must first
    confirm the password or an OTP via POST /api/v1/auth/step-up; for the
    next few minutes it may then call the route. Sessions opened with a
    password or OTP pass straight through.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        token = get_current_token()
        if token and token.step_up_required and not token._is_recently_verified():
            return api_error(
                'Confirm your password or OTP to continue.', status=403, code='step_up_required')
        return func(*args, **kwargs)
    return wrapper


def require_recent_auth(func):
    """Use below @require_auth on the most sensitive routes (e.g. face
    enrolment). Every session, however it was opened, must have confirmed
    the password or an OTP in the last few minutes - logging in with a
    password or OTP counts - so a long-lived stolen token alone isn't
    enough.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        token = get_current_token()
        if not token or not token._is_recently_verified():
            return api_error(
                'Confirm your password or OTP to continue.', status=403, code='step_up_required')
        return func(*args, **kwargs)
    return wrapper


def get_current_token():
    """The bxi.api.token (sudo) the current @require_auth request came in
    with, or an empty recordset outside such a request."""
    auth_header = request.httprequest.headers.get('Authorization', '')
    raw_token = auth_header[7:] if auth_header.startswith('Bearer ') else None
    Token = request.env['bxi.api.token'].sudo()
    if not raw_token:
        return Token
    return Token.search([('token_hash', '=', Token._hash(raw_token)), ('active', '=', True)], limit=1)
