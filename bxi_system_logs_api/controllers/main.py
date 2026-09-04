# -*- coding: utf-8 -*-

from odoo import fields as odoo_fields
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth

VALUE_FIELDS = ['integer', 'float', 'char', 'text', 'datetime']


def _first_value(tracking, prefix):
    for kind in VALUE_FIELDS:
        value = getattr(tracking, f'{prefix}_value_{kind}')
        if value not in (False, None, ''):
            return value
    return None


class BxiSystemLogsApiController(http.Controller):

    @http.route('/api/v1/admin/system-logs', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def system_logs(self, model=None, res_id=None, date_from=None, date_to=None, limit=None, offset=None, **kwargs):
        if not request.env.user.has_group('base.group_system'):
            return api_error('Not authorized. Full administration access is required.', status=403, code='forbidden')

        domain = []
        if model:
            domain.append(('mail_message_id.model', '=', model))
        if res_id:
            res_id_val, error = parse_int(res_id, 'res_id')
            if error:
                return error
            domain.append(('mail_message_id.res_id', '=', res_id_val))
        if date_from:
            domain.append(('mail_message_id.date', '>=', odoo_fields.Datetime.from_string(date_from)))
        if date_to:
            domain.append(('mail_message_id.date', '<=', odoo_fields.Datetime.from_string(date_to)))

        limit_val = 100
        if limit:
            limit_val, error = parse_int(limit, 'limit')
            if error:
                return error
            limit_val = min(limit_val, 200)
        offset_val = 0
        if offset:
            offset_val, error = parse_int(offset, 'offset')
            if error:
                return error

        trackings = request.env['mail.tracking.value'].sudo().search(
            domain, order='id desc', limit=limit_val, offset=offset_val)

        return api_response({
            'entries': [{
                'id': t.id,
                'date': t.mail_message_id.date.isoformat() if t.mail_message_id.date else None,
                'author': t.mail_message_id.author_id.display_name,
                'model': t.mail_message_id.model,
                'res_id': t.mail_message_id.res_id,
                'field': t.field_id.field_description,
                'old_value': _first_value(t, 'old'),
                'new_value': _first_value(t, 'new'),
            } for t in trackings],
        })
