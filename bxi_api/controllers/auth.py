# -*- coding: utf-8 -*-

"""Shared API auth decorator and response envelope.

Every Orbix API controller - in this module or any other bxi_* module that
depends on it - should use `api_response`/`api_error` for its return value
and `@require_auth` on any route that needs to know which app user is
calling, instead of building its own auth or response shape.
"""

from functools import wraps

from odoo.http import request


def api_response(data=None, status=200, meta=None):
    body = {'success': True, 'data': data if data is not None else {}}
    if meta:
        body['meta'] = meta
    return request.make_json_response(body, status=status)


def api_error(message, status=400, code=None):
    body = {'success': False, 'error': {'message': message, 'code': code or status}}
    return request.make_json_response(body, status=status)


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
        user = request.env['bxi.api.token'].sudo()._verify_token(raw_token)
        if not user:
            return api_error('Invalid or expired token.', status=401, code='unauthorized')
        request.update_env(user=user.id)
        return func(*args, **kwargs)
    return wrapper
