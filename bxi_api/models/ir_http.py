# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

"""CORS for the /api/v1 namespace.

The web portal is served from its own origin and calls the API from the
browser, so every API response needs CORS headers and the browser's
OPTIONS preflight has to be answered before it reaches a controller: Odoo
routes OPTIONS to the same endpoint as the real call, where login crashes
on the empty body and @require_auth answers 401, and the browser then
refuses to send the real request.

The API authenticates with bearer tokens, never cookies, so credentials
are not allowed and '*' is a safe default. Set the system parameter
`bxi_api.cors_allowed_origins` to a comma-separated list of origins
(e.g. `https://portal.orbixschools.com`) to allow only those.
"""

import werkzeug.exceptions

from odoo import models
from odoo.http import Response, request

API_PREFIX = '/api/v1/'
CORS_ORIGINS_PARAM = 'bxi_api.cors_allowed_origins'
CORS_MAX_AGE = 60 * 60 * 24
# Copied from the request onto error responses, which Odoo builds without
# the headers collected in request.future_response.
CORS_RESPONSE_HEADERS = ('Access-Control-Allow-Origin', 'Access-Control-Expose-Headers', 'Vary')


def _is_api_request():
    return request.httprequest.path.startswith(API_PREFIX)


def _cors_headers():
    """The CORS headers for the current request, or {} when it carries no
    Origin (the mobile app, server-to-server calls) or its Origin is not
    allowed."""
    origin = request.httprequest.headers.get('Origin')
    if not origin:
        return {}
    allowed = request.env['ir.config_parameter'].sudo().get_param(CORS_ORIGINS_PARAM) or '*'
    allowed = {o.strip().rstrip('/') for o in allowed.split(',') if o.strip()}
    if '*' in allowed:
        headers = {'Access-Control-Allow-Origin': '*'}
    elif origin in allowed:
        headers = {'Access-Control-Allow-Origin': origin, 'Vary': 'Origin'}
    else:
        return {}
    # api_file_response() names the download here.
    headers['Access-Control-Expose-Headers'] = 'Content-Disposition'
    if request.httprequest.method == 'OPTIONS':
        headers.update({
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Authorization, Content-Type, Accept, Origin, X-Requested-With',
            'Access-Control-Max-Age': str(CORS_MAX_AGE),
        })
    return headers


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _pre_dispatch(cls, rule, args):
        if _is_api_request():
            request.future_response.headers.update(_cors_headers())
            if request.httprequest.method == 'OPTIONS':
                werkzeug.exceptions.abort(Response(status=204))
        super()._pre_dispatch(rule, args)

    @classmethod
    def _handle_error(cls, exception):
        response = super()._handle_error(exception)
        if not _is_api_request():
            return response
        # Reuse what _pre_dispatch computed rather than reading the config
        # parameter again from a transaction the error may have broken.
        cors = [(k, v) for k, v in request.future_response.headers if k in CORS_RESPONSE_HEADERS]
        if cors:
            if isinstance(response, werkzeug.exceptions.HTTPException):
                response = response.get_response()
            response.headers.update(cors)
        return response
