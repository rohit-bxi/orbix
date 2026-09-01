# -*- coding: utf-8 -*-

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth


def _user_can_access_student(env, student):
    """A caller may act on a student's fees if they are staff (any regular
    backend user - the fee models' own ir.rule/ACL still applies on top of
    this) or a parent linked to that student.
    """
    user = env.user
    if user.has_group('base.group_user'):
        return True
    return bool(env['op.parent'].sudo().search_count([
        ('user_id', '=', user.id), ('student_ids', 'in', student.id),
    ]))


class BxiOnlineFeePaymentController(http.Controller):

    @http.route('/api/v1/payments/summary', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def summary(self, student_id=None, **kwargs):
        if not student_id:
            return api_error('student_id is required.', status=400, code='missing_student_id')
        student = request.env['op.student'].sudo().browse(int(student_id))
        if not student.exists():
            return api_error('Student not found.', status=404, code='not_found')
        if not _user_can_access_student(request.env, student):
            return api_error('Not authorized for this student.', status=403, code='forbidden')

        return api_response(student.get_fee_payment_summary())

    @http.route('/api/v1/payments/create-order', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_order(self, **kwargs):
        payload = request.get_json_data()
        fees_detail_id = payload.get('fees_detail_id')
        amount = payload.get('amount')
        if not fees_detail_id or not amount:
            return api_error('fees_detail_id and amount are required.', status=400, code='missing_fields')

        detail = request.env['op.student.fees.details'].sudo().browse(int(fees_detail_id))
        if not detail.exists():
            return api_error('Fee line not found.', status=404, code='not_found')
        if not _user_can_access_student(request.env, detail.student_id):
            return api_error('Not authorized for this student.', status=403, code='forbidden')

        try:
            order = request.env['bxi.payment.order']._create_for_fee_line(detail, float(amount), request.env.user)
        except UserError as exc:
            return api_error(str(exc), status=400, code='invalid_amount')

        if not order:
            return api_error('Could not create the payment order with the gateway.', status=502, code='gateway_error')

        return api_response({
            'payment_order_id': order.id,
            'razorpay_order_id': order.razorpay_order_id,
            'amount': order.amount,
            'currency': order.currency_id.name,
        })

    @http.route('/api/v1/payments/verify', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def verify(self, **kwargs):
        payload = request.get_json_data()
        payment_order_id = payload.get('payment_order_id')
        razorpay_payment_id = payload.get('razorpay_payment_id')
        razorpay_signature = payload.get('razorpay_signature')
        if not payment_order_id or not razorpay_payment_id or not razorpay_signature:
            return api_error(
                'payment_order_id, razorpay_payment_id and razorpay_signature are required.',
                status=400, code='missing_fields')

        order = request.env['bxi.payment.order'].sudo().browse(int(payment_order_id))
        if not order.exists() or order.user_id.id != request.env.user.id:
            return api_error('Payment order not found.', status=404, code='not_found')

        ok = order._mark_paid_from_client(razorpay_payment_id, razorpay_signature)
        if not ok:
            return api_error('Payment signature could not be verified.', status=400, code='invalid_signature')
        return api_response({'status': order.status})

    @http.route('/api/v1/payments/webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def webhook(self, **kwargs):
        raw_body = request.httprequest.get_data()
        signature = request.httprequest.headers.get('X-Razorpay-Signature', '')
        client = request.env['bxi.razorpay.client'].sudo()
        if not client.verify_webhook_signature(raw_body, signature):
            return api_error('Invalid webhook signature.', status=400, code='invalid_signature')

        payload = request.get_json_data()
        payment_entity = payload.get('payload', {}).get('payment', {}).get('entity', {})
        razorpay_order_id = payment_entity.get('order_id')
        razorpay_payment_id = payment_entity.get('id')
        if not razorpay_order_id or not razorpay_payment_id:
            return api_error('Malformed webhook payload.', status=400, code='malformed_payload')

        order = request.env['bxi.payment.order'].sudo().search([('razorpay_order_id', '=', razorpay_order_id)], limit=1)
        if not order:
            # Not one of our orders (or a webhook for a different feature) -
            # acknowledge with 200 anyway so Razorpay doesn't keep retrying.
            return api_response({'ignored': True})

        order._mark_paid_from_webhook(razorpay_payment_id)
        return api_response({'status': order.status})
