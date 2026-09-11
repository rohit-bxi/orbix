# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import get_own_student_ids, parse_pagination, safe_create

STAFF_GROUP = 'bxi_uniform_management.group_uniform_staff'
MANAGER_GROUP = 'bxi_uniform_management.group_uniform_manager'


def _is_uniform_staff(user):
    return user.has_group(STAFF_GROUP) or user.has_group(MANAGER_GROUP)


def _can_access_patron(env, record):
    if _is_uniform_staff(env.user):
        return True
    if record.student_id and record.student_id.id in get_own_student_ids(env):
        return True
    if record.faculty_id and record.faculty_id.user_id.id == env.user.id:
        return True
    return False


def _order_dict(order):
    return {
        'id': order.id,
        'name': order.name,
        'type': order.type,
        'order_date': order.order_date and order.order_date.isoformat(),
        'patron_type': order.patron_type,
        'patron_name': order.patron_name,
        'total_amount': order.total_amount,
        'state': order.state,
        'invoice_payment_state': order.invoice_payment_state,
        'lines': [{
            'id': l.id, 'product': l.product_id.display_name, 'quantity': l.quantity,
            'price_unit': l.price_unit, 'price_subtotal': l.price_subtotal,
        } for l in order.order_line_ids],
    }


def _stock_dict(stock):
    return {
        'id': stock.id,
        'product': stock.product_id.display_name,
        'quantity_on_hand': stock.quantity_on_hand,
        'reorder_level': stock.reorder_level,
        'is_low_stock': stock.is_low_stock,
    }


class BxiApiSupportUniformController(http.Controller):

    @http.route('/api/v1/uniform/orders', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_orders(self, **kwargs):
        user = request.env.user
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        if _is_uniform_staff(user):
            domain = []
        else:
            own_student_ids = get_own_student_ids(request.env)
            domain = ['|', ('student_id', 'in', own_student_ids), ('faculty_id.user_id', '=', user.id)]
        Order = request.env['bxi.uniform.order'].sudo()
        total = Order.search_count(domain)
        orders = Order.search(domain, limit=limit, offset=offset, order='order_date desc')
        return api_response(
            {'orders': [_order_dict(o) for o in orders]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/uniform/orders/<int:order_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_order(self, order_id, **kwargs):
        order = request.env['bxi.uniform.order'].sudo().browse(order_id)
        if not order.exists():
            return api_error('Order not found.', status=404, code='not_found')
        if not _can_access_patron(request.env, order):
            return api_error('Not authorized for this order.', status=403, code='forbidden')
        return api_response(_order_dict(order))

    @http.route('/api/v1/uniform/orders', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_order(self, **kwargs):
        payload = request.get_json_data() or {}
        student_id = payload.get('student_id')
        faculty_id = payload.get('faculty_id')
        if not student_id and not faculty_id:
            return api_error('student_id or faculty_id is required.', status=400, code='missing_patron')

        user = request.env.user
        if student_id and not _is_uniform_staff(user) and int(student_id) not in get_own_student_ids(request.env):
            return api_error('Not authorized for this student.', status=403, code='forbidden')
        if faculty_id and not _is_uniform_staff(user):
            faculty = request.env['op.faculty'].sudo().browse(int(faculty_id))
            if faculty.user_id.id != user.id:
                return api_error('Not authorized for this faculty member.', status=403, code='forbidden')

        vals = {'type': 'faculty' if faculty_id else 'student'}
        if student_id:
            vals['student_id'] = student_id
        if faculty_id:
            vals['faculty_id'] = faculty_id
        if payload.get('lines'):
            Product = request.env['product.product'].sudo()
            vals['order_line_ids'] = [(0, 0, {
                'product_id': line['product_id'], 'quantity': line.get('quantity', 1.0),
                # action_load_from_policy aside, a manually-built order only
                # gets a price_unit via a UI onchange that create() never
                # triggers - set it explicitly here.
                'price_unit': Product.browse(line['product_id']).list_price,
            }) for line in payload['lines']]
        order, error = safe_create(request.env['bxi.uniform.order'].sudo(), vals)
        if error:
            return error
        return api_response(_order_dict(order), status=201)

    @http.route('/api/v1/uniform/orders/<int:order_id>/load-from-policy', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def load_from_policy(self, order_id, **kwargs):
        return self._transition(order_id, 'action_load_from_policy', require_owner=True)

    @http.route('/api/v1/uniform/orders/<int:order_id>/confirm', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def confirm_order(self, order_id, **kwargs):
        return self._transition(order_id, 'action_confirm', require_owner=True)

    @http.route('/api/v1/uniform/orders/<int:order_id>/mark-issued', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def mark_issued_order(self, order_id, **kwargs):
        return self._transition(order_id, 'action_mark_issued')

    @http.route('/api/v1/uniform/orders/<int:order_id>/force-issue', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def force_issue_order(self, order_id, **kwargs):
        return self._transition(order_id, 'action_force_issue')

    @http.route('/api/v1/uniform/orders/<int:order_id>/set-draft', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def set_draft_order(self, order_id, **kwargs):
        return self._transition(order_id, 'action_set_draft')

    @http.route('/api/v1/uniform/orders/<int:order_id>/cancel', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def cancel_order(self, order_id, **kwargs):
        order = request.env['bxi.uniform.order'].sudo().browse(order_id)
        if not order.exists():
            return api_error('Order not found.', status=404, code='not_found')
        if not _can_access_patron(request.env, order):
            return api_error('Not authorized for this order.', status=403, code='forbidden')
        payload = request.get_json_data() or {}
        if payload.get('cancel_reason'):
            order.cancel_reason = payload['cancel_reason']
        _, error = call_action(order, 'action_cancel')
        if error:
            return error
        return api_response(_order_dict(order))

    def _transition(self, order_id, method_name, require_owner=False):
        order = request.env['bxi.uniform.order'].sudo().browse(order_id)
        if not order.exists():
            return api_error('Order not found.', status=404, code='not_found')
        if require_owner and not _can_access_patron(request.env, order):
            return api_error('Not authorized for this order.', status=403, code='forbidden')
        if not require_owner and not _is_uniform_staff(request.env.user):
            return api_error('Not authorized for this action.', status=403, code='forbidden')
        _, error = call_action(order, method_name)
        if error:
            return error
        return api_response(_order_dict(order))

    @http.route('/api/v1/uniform/orders/<int:order_id>/exchange', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def exchange_order_line(self, order_id, **kwargs):
        if not _is_uniform_staff(request.env.user):
            return api_error('Not authorized to exchange uniform items.', status=403, code='forbidden')
        order = request.env['bxi.uniform.order'].sudo().browse(order_id)
        if not order.exists():
            return api_error('Order not found.', status=404, code='not_found')
        payload = request.get_json_data() or {}
        if not payload.get('order_line_id'):
            return api_error('order_line_id is required.', status=400, code='missing_order_line_id')
        if not payload.get('new_product_id'):
            return api_error('new_product_id is required.', status=400, code='missing_new_product_id')

        line = order.order_line_ids.filtered(lambda l: l.id == payload['order_line_id'])
        if not line:
            return api_error('Order line not found on this order.', status=404, code='not_found')
        wizard, error = safe_create(request.env['bxi.uniform.exchange.wizard'].sudo(), {
            'order_line_id': line.id, 'new_product_id': payload['new_product_id'], 'note': payload.get('note'),
        })
        if error:
            return error
        _, error = call_action(wizard, 'action_exchange')
        if error:
            return error
        return api_response(_order_dict(order))

    @http.route('/api/v1/uniform/stock', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_stock(self, **kwargs):
        if not _is_uniform_staff(request.env.user):
            return api_error('Not authorized to view uniform stock.', status=403, code='forbidden')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        Stock = request.env['bxi.uniform.stock'].sudo()
        total = Stock.search_count([])
        stock = Stock.search([], limit=limit, offset=offset)
        return api_response(
            {'stock': [_stock_dict(s) for s in stock]}, meta={'total': total, 'limit': limit, 'offset': offset})
