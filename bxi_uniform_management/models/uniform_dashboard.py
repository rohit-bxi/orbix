# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from collections import Counter

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

MONTH_WINDOW = 6
ORDER_LIST_LIMIT = 10
TOP_PRODUCTS_LIMIT = 8
LOW_STOCK_LIMIT = 5
RECENT_ACTIVITY_LIMIT = 8

ORDER_STATUS_KIND = {
    'draft': 'info',
    'confirmed': 'warning',
    'issued': 'success',
    'cancelled': 'danger',
}
MOVE_TYPE_KIND = {
    'receipt': 'success',
    'issue': 'info',
    'return': 'warning',
    'adjustment': 'info',
}


class UniformDashboard(models.AbstractModel):
    """Server-side aggregation for the Uniform Dashboard client action.
    Every number here is a live query against bxi.uniform.order /
    bxi.uniform.stock / bxi.uniform.stock.move - nothing is cached, so
    the dashboard always matches the underlying list views.
    """
    _name = 'bxi.uniform.dashboard'
    _description = 'Uniform Dashboard'

    def _month_bounds(self, months_ago=0):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1) - relativedelta(months=months_ago)
        month_end = month_start + relativedelta(months=1) - relativedelta(days=1)
        return month_start, month_end

    @api.model
    def get_dashboard_data(self):
        Order = self.env['bxi.uniform.order'].sudo()
        orders = Order.search([])
        return {
            'kpis': self._get_kpis(orders),
            'order_list': self._get_order_list(Order),
            'charts': {
                'status_distribution': self._get_status_distribution(orders),
                'stock_health': self._get_stock_health(),
                'top_products': self._get_top_products(orders),
                'monthly_revenue_trend': self._get_monthly_revenue_trend(orders),
            },
            'low_stock_items': self._get_low_stock_items(),
            'stats': self._get_secondary_stats(orders),
            'recent_activity': self._get_recent_activity(),
        }

    def _get_kpis(self, orders):
        today = fields.Date.context_today(self)
        orders_today = orders.filtered(lambda o: o.order_date == today)
        orders_pending_issue = orders.filtered(lambda o: o.state == 'confirmed')
        total_amount_today = sum(orders_today.filtered(lambda o: o.state != 'cancelled').mapped('total_amount'))
        issued_today = orders_today.filtered(lambda o: o.state == 'issued')
        return {
            'orders_today': {'value': len(orders_today)},
            'orders_pending_issue': {'value': len(orders_pending_issue)},
            'total_amount_today': {'value': total_amount_today},
            'issue_completion_rate': {
                'value': round(len(issued_today) / len(orders_today) * 100.0, 1) if orders_today else 0.0,
            },
        }

    def _get_order_list(self, Order):
        records = Order.search([], order='write_date desc', limit=ORDER_LIST_LIMIT)
        return [{
            'id': o.id,
            'patron_name': o.patron_name or '',
            'total_amount': o.total_amount,
            'state': o.state,
            'order_date': fields.Date.to_string(o.order_date) if o.order_date else '',
        } for o in records]

    def _get_status_distribution(self, orders):
        status_labels = dict(orders._fields['state'].selection)
        counter = Counter(orders.mapped('state'))
        ordered = [key for key, _label in orders._fields['state'].selection if key in counter]
        return {
            'labels': [status_labels.get(k, k) for k in ordered],
            'values': [counter[k] for k in ordered],
        }

    def _get_stock_health(self):
        Stock = self.env['bxi.uniform.stock'].sudo()
        total = Stock.search_count([])
        low = Stock.search_count([('is_low_stock', '=', True)])
        return {'total': total, 'low_stock': low, 'healthy': max(total - low, 0)}

    def _get_top_products(self, orders):
        Line = self.env['bxi.uniform.order.line'].sudo()
        lines = Line.search([('order_id', 'in', orders.filtered(lambda o: o.state != 'cancelled').ids)])
        counter = Counter()
        for line in lines:
            counter[line.product_id.display_name] += line.quantity
        ordered = sorted(counter, key=lambda k: counter[k], reverse=True)[:TOP_PRODUCTS_LIMIT]
        return {
            'labels': ordered,
            'values': [round(counter[k], 1) for k in ordered],
        }

    def _get_monthly_revenue_trend(self, orders):
        labels, values = [], []
        non_cancelled = orders.filtered(lambda o: o.state != 'cancelled')
        for i in range(MONTH_WINDOW - 1, -1, -1):
            month_start, month_end = self._month_bounds(i)
            month_records = non_cancelled.filtered(
                lambda o: o.order_date and month_start <= o.order_date <= month_end)
            labels.append(month_start.strftime('%b'))
            values.append(sum(month_records.mapped('total_amount')))
        return {'labels': labels, 'values': values}

    def _get_low_stock_items(self):
        Stock = self.env['bxi.uniform.stock'].sudo()
        items = Stock.search([('is_low_stock', '=', True)], order='quantity_on_hand asc', limit=LOW_STOCK_LIMIT)
        return [{
            'product_name': s.product_id.display_name,
            'quantity_on_hand': s.quantity_on_hand,
            'reorder_level': s.reorder_level,
        } for s in items]

    def _get_secondary_stats(self, orders):
        Stock = self.env['bxi.uniform.stock'].sudo()
        month_start, _month_end = self._month_bounds(0)
        next_month_start = month_start + relativedelta(months=1)

        low_stock_item_count = Stock.search_count([('is_low_stock', '=', True)])
        orders_issued_month = len(orders.filtered(
            lambda o: o.state == 'issued' and o.order_date
            and month_start <= o.order_date < next_month_start))
        pending_invoices = len(orders.filtered(
            lambda o: o.invoice_id and o.invoice_payment_state not in ('paid', 'in_payment')))
        return {
            'low_stock_item_count': low_stock_item_count,
            'orders_issued_month': orders_issued_month,
            'pending_invoices': pending_invoices,
        }

    def _get_recent_activity(self):
        activities = []

        Order = self.env['bxi.uniform.order'].sudo()
        order_labels = dict(Order._fields['state'].selection)
        for order in Order.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': 'Order %s (%s) - %s' % (
                    order.name, order.patron_name or '', order_labels.get(order.state, order.state)),
                'date': fields.Datetime.to_string(order.write_date),
                'kind': ORDER_STATUS_KIND.get(order.state, 'info'),
            })

        Move = self.env['bxi.uniform.stock.move'].sudo()
        move_labels = dict(Move._fields['move_type'].selection)
        for move in Move.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': '%s - %s (%s)' % (
                    move_labels.get(move.move_type, move.move_type),
                    move.product_id.display_name or '', move.quantity),
                'date': fields.Datetime.to_string(move.write_date),
                'kind': MOVE_TYPE_KIND.get(move.move_type, 'info'),
            })

        activities.sort(key=lambda a: a['date'], reverse=True)
        return activities[:RECENT_ACTIVITY_LIMIT]
