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
import time
from collections import defaultdict, deque
from functools import wraps

import odoo.modules.module
from odoo.exceptions import AccessError, UserError
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


def call_action(record, method_name, **kwargs):
    """Call an `action_*` transition method on `record`, translating the
    exceptions those methods already raise for an illegal transition or a
    permission problem into the standard API error envelope, instead of
    every controller re-implementing the same try/except.

    Returns (result, None) on success or (None, api_error(...)) on failure -
    callers should `return error` immediately when the second item isn't
    None, the same way `parse_int` is used.
    """
    try:
        return getattr(record, method_name)(**kwargs), None
    except AccessError as exc:
        # AccessError subclasses UserError in this Odoo version, so this
        # branch must come first - otherwise every AccessError would match
        # `except UserError` below and get reported as 400 instead of 403.
        return None, api_error(str(exc), status=403, code='forbidden')
    except UserError as exc:
        return None, api_error(str(exc), status=400, code='invalid_transition')


def require_auth(func):
    """Validates the `Authorization: Bearer <token>` header against
    bxi.api.token and, on success, runs the wrapped route with
    `request.env` switched to that token's user (so ir.rule/ACLs apply as
    that user, the same as a normal Odoo request). On failure, returns a
    401 envelope without calling the wrapped route at all.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth_header = request.httprequest.headers.get('Authorization', '')
        raw_token = auth_header[7:] if auth_header.startswith('Bearer ') else None
        token = request.env['bxi.api.token'].sudo()._verify_token_record(raw_token)
        if not token:
            return api_error('Invalid or expired token.', status=401, code='unauthorized')
        request.update_env(user=token.user_id.id)
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
