# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, call_action, require_auth

from .common import get_own_student_ids, parse_pagination, safe_create

STAFF_GROUP = 'bxi_school_canteen_management.group_canteen_staff'
MANAGER_GROUP = 'bxi_school_canteen_management.group_canteen_manager'


def _is_canteen_staff(user):
    return user.has_group(STAFF_GROUP) or user.has_group(MANAGER_GROUP)


def _can_access_patron(env, record):
    if _is_canteen_staff(env.user):
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
        'order_datetime': order.order_datetime and order.order_datetime.isoformat(),
        'patron_type': order.patron_type,
        'patron_name': order.patron_name,
        'total_amount': order.total_amount,
        'wallet_balance': order.wallet_balance,
        'state': order.state,
        'lines': [{
            'id': l.id, 'product': l.product_id.display_name, 'quantity': l.quantity,
            'price_unit': l.price_unit, 'price_subtotal': l.price_subtotal,
        } for l in order.order_line_ids],
    }


def _wallet_dict(wallet):
    return {
        'id': wallet.id,
        'patron_type': wallet.patron_type,
        'patron_name': wallet.patron_name,
        'balance': wallet.balance,
        'is_low_balance': wallet.is_low_balance,
    }


class BxiApiSupportCanteenController(http.Controller):

    @http.route('/api/v1/canteen/orders', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_orders(self, **kwargs):
        user = request.env.user
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        if _is_canteen_staff(user):
            domain = []
        else:
            own_student_ids = get_own_student_ids(request.env)
            domain = ['|', ('student_id', 'in', own_student_ids), ('faculty_id.user_id', '=', user.id)]
        Order = request.env['bxi.canteen.order'].sudo()
        total = Order.search_count(domain)
        orders = Order.search(domain, limit=limit, offset=offset, order='order_datetime desc')
        return api_response(
            {'orders': [_order_dict(o) for o in orders]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/canteen/orders/<int:order_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_order(self, order_id, **kwargs):
        order = request.env['bxi.canteen.order'].sudo().browse(order_id)
        if not order.exists():
            return api_error('Order not found.', status=404, code='not_found')
        if not _can_access_patron(request.env, order):
            return api_error('Not authorized for this order.', status=403, code='forbidden')
        return api_response(_order_dict(order))

    @http.route('/api/v1/canteen/orders', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_order(self, **kwargs):
        payload = request.get_json_data() or {}
        lines = payload.get('lines') or []
        if not lines:
            return api_error('lines is required.', status=400, code='missing_lines')
        student_id = payload.get('student_id')
        faculty_id = payload.get('faculty_id')
        if not student_id and not faculty_id:
            return api_error('student_id or faculty_id is required.', status=400, code='missing_patron')

        user = request.env.user
        if student_id and not _is_canteen_staff(user) and int(student_id) not in get_own_student_ids(request.env):
            return api_error('Not authorized for this student.', status=403, code='forbidden')
        if faculty_id and not _is_canteen_staff(user):
            faculty = request.env['op.faculty'].sudo().browse(int(faculty_id))
            if faculty.user_id.id != user.id:
                return api_error('Not authorized for this faculty member.', status=403, code='forbidden')

        Product = request.env['product.product'].sudo()
        vals = {'order_line_ids': [(0, 0, {
            'product_id': line['product_id'], 'quantity': line.get('quantity', 1.0),
            # The model only defaults price_unit from a UI onchange, which
            # never fires on a plain create() - set it explicitly here.
            'price_unit': Product.browse(line['product_id']).list_price,
        }) for line in lines]}
        if student_id:
            vals['student_id'] = student_id
        if faculty_id:
            vals['faculty_id'] = faculty_id
        order, error = safe_create(request.env['bxi.canteen.order'].sudo(), vals)
        if error:
            return error
        return api_response(_order_dict(order), status=201)

    @http.route('/api/v1/canteen/orders/<int:order_id>/confirm', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def confirm_order(self, order_id, **kwargs):
        return self._transition(order_id, 'action_confirm', require_owner=True)

    @http.route('/api/v1/canteen/orders/<int:order_id>/force-confirm', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def force_confirm_order(self, order_id, **kwargs):
        return self._transition(order_id, 'action_force_confirm')

    @http.route('/api/v1/canteen/orders/<int:order_id>/preparing', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def preparing_order(self, order_id, **kwargs):
        return self._transition(order_id, 'action_preparing')

    @http.route('/api/v1/canteen/orders/<int:order_id>/ready', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def ready_order(self, order_id, **kwargs):
        return self._transition(order_id, 'action_ready')

    @http.route('/api/v1/canteen/orders/<int:order_id>/served', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def served_order(self, order_id, **kwargs):
        return self._transition(order_id, 'action_served')

    @http.route('/api/v1/canteen/orders/<int:order_id>/cancel', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def cancel_order(self, order_id, **kwargs):
        order = request.env['bxi.canteen.order'].sudo().browse(order_id)
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
        order = request.env['bxi.canteen.order'].sudo().browse(order_id)
        if not order.exists():
            return api_error('Order not found.', status=404, code='not_found')
        if require_owner and not _can_access_patron(request.env, order):
            return api_error('Not authorized for this order.', status=403, code='forbidden')
        if not require_owner and not _is_canteen_staff(request.env.user):
            return api_error('Not authorized for this action.', status=403, code='forbidden')
        _, error = call_action(order, method_name)
        if error:
            return error
        return api_response(_order_dict(order))

    @http.route('/api/v1/canteen/wallets', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_wallets(self, **kwargs):
        user = request.env.user
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        if _is_canteen_staff(user):
            domain = []
        else:
            own_student_ids = get_own_student_ids(request.env)
            domain = ['|', ('student_id', 'in', own_student_ids), ('faculty_id.user_id', '=', user.id)]
        Wallet = request.env['bxi.canteen.wallet'].sudo()
        total = Wallet.search_count(domain)
        wallets = Wallet.search(domain, limit=limit, offset=offset)
        return api_response(
            {'wallets': [_wallet_dict(w) for w in wallets]}, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/canteen/wallets/<int:wallet_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_wallet(self, wallet_id, **kwargs):
        wallet = request.env['bxi.canteen.wallet'].sudo().browse(wallet_id)
        if not wallet.exists():
            return api_error('Wallet not found.', status=404, code='not_found')
        if not _can_access_patron(request.env, wallet):
            return api_error('Not authorized for this wallet.', status=403, code='forbidden')
        return api_response(_wallet_dict(wallet))

    @http.route('/api/v1/canteen/wallet/topup', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def topup_wallet(self, **kwargs):
        payload = request.get_json_data() or {}
        student_id = payload.get('student_id')
        faculty_id = payload.get('faculty_id')
        if payload.get('amount') is None:
            return api_error('amount is required.', status=400, code='missing_amount')
        if not student_id and not faculty_id:
            return api_error('student_id or faculty_id is required.', status=400, code='missing_patron')

        user = request.env.user
        if student_id and not _is_canteen_staff(user) and int(student_id) not in get_own_student_ids(request.env):
            return api_error('Not authorized for this student.', status=403, code='forbidden')
        if faculty_id and not _is_canteen_staff(user):
            faculty = request.env['op.faculty'].sudo().browse(int(faculty_id))
            if faculty.user_id.id != user.id:
                return api_error('Not authorized for this faculty member.', status=403, code='forbidden')

        vals = {
            'patron_type': 'faculty' if faculty_id else 'student',
            'amount': payload['amount'],
            'payment_method': payload.get('payment_method', 'cash'),
            'post_to_accounting': payload.get('post_to_accounting', False),
        }
        if student_id:
            vals['student_id'] = student_id
        if faculty_id:
            vals['faculty_id'] = faculty_id
        if payload.get('journal_id'):
            vals['journal_id'] = payload['journal_id']
        wizard, error = safe_create(request.env['bxi.canteen.wallet.topup.wizard'].sudo(), vals)
        if error:
            return error
        _, error = call_action(wizard, 'action_topup')
        if error:
            return error
        patron_domain = [('student_id', '=', student_id)] if student_id else [('faculty_id', '=', faculty_id)]
        wallet = request.env['bxi.canteen.wallet'].sudo().search(patron_domain, limit=1)
        return api_response(_wallet_dict(wallet))
